# TCP_Client_async_q_patched.py
# Integrated enhancements:
# - Fix for UnboundLocalError in sender()
# - Adaptive transparent vs normal mode
# - Transparent stream reopen helper (+ escape with "+++")
# - Link watchdog with optional hard reset
# - Rate limiting (token-bucket) for messages and bytes
# - Inter-AT command gap enforcement
# - Byte-budgeted send_at() to avoid starving the event loop
#
# Customize the CONFIG section for your setup.
#
# Tested conceptually for ESP8266/ESP32 AT firmware. Adjust pins/timeouts as needed.

import uasyncio as asyncio
import utime as time
import ure as re
from queue import Queue
import ubinascii
import uhashlib
import ujson

try:
    from machine import UART, Pin
except ImportError:
    # For desktop testing stubs (won't actually run, but allows syntax checking)
    UART = None
    class Pin:
        OUT = 1
        def __init__(self, *a, **k): pass
        def value(self, v=None): return 1

# -----------------------------
# CONFIG
# -----------------------------
# UART config for the modem (adjust to your board)
UART_PORT = 1          # e.g., 0, 1, 2 depending on board
UART_BAUD = 115200
UART_TX_PIN = None     # set to pin number if your board requires explicit mapping
UART_RX_PIN = None

# Optional modem enable/reset pin (set to a real pin or leave None)
MODEM_EN_PIN = None    # e.g., 5 on some boards

# Wi-Fi / TCP target
SSID = "Cudy24G"
PWD  = "ZAnne19991214"
IP   = "192.168.10.250"  # your TCP server IP
PORT = 8080             # your TCP server port

# Test generator settings
iTestMsgCount = 2
testMsgLength = 1

# Rate control config
BYTES_PER_SEC      = 2048   # throttle raw throughput (0 = unlimited)
MSG_PER_SEC        = 10     # throttle number of messages/ATs (0 = unlimited)
INTER_CMD_GAP_MS   = 35     # minimum gap between AT commands
MAX_INFLIGHT_SENDS = 1      # backpressure: limit concurrent sends

# Watchdog config
MAX_FAILS_BEFORE_HARD = 3   # after this, try hard reset (if MODEM_EN_PIN is set)
WATCHDOG_CHECK_MS     = 5000
WATCHDOG_IDLE_MS      = 15000

# send_at byte-budget defaults
SEND_AT_MAX_BYTES     = 4096
SEND_AT_CHUNK_SIZE    = 256
SEND_AT_MAX_LINE      = 512

# -----------------------------
# Globals / shared state
# -----------------------------
TRANSPARENT_MODE  = [False]  # whether we intend to use transparent data mode
TRANSPARENT_READY = [False]  # whether the '>' prompt is active (data mode open)

LAST_TX_MS = [0]             # last time we wrote to UART
LAST_RX_MS = [0]             # last time we received from UART
CONSEC_FAILS = [0]
WATCHDOG_ENABLED = [True]
CANDIDATE_UARTS = [0, 1, 2]          # try what your board supports
CANDIDATE_BAUDS = [115200, 9600, 230400, 57600]  # common ESP-AT bauds

# Token buckets and locks initialized later (after uart)
byte_bucket = None
msg_bucket = None
cmd_lock = None
send_sem = None
_last_cmd_ms = [0]
_iMsgId = 1
uart = None
MODEM_EN = None
_out_hash_md5 = uhashlib.sha256()
_pending = {}  # e.g. {'OK': Future, '>': Future, 'ERROR': Future}
_at_lock = asyncio.Lock()

class Semaphore:
    def __init__(self, value=1):
        self._value = value
        self._waiters = []

    async def acquire(self):
        while self._value <= 0:
            ev = asyncio.Event()
            self._waiters.append(ev)
            await ev.wait()
        self._value -= 1

    def release(self):
        self._value += 1
        if self._waiters:
            ev = self._waiters.pop(0)
            ev.set()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.release()

# -----------------------------
# Token-bucket limiter
# -----------------------------
class AsyncTokenBucket:
    def __init__(self, rate_per_sec=0, burst=0):
        self.rate = rate_per_sec
        self.capacity = max(burst, rate_per_sec) if rate_per_sec > 0 else 0
        self.tokens = self.capacity
        self.last = time.ticks_ms()
        self._lock = asyncio.Lock()

    async def _refill(self):
        now = time.ticks_ms()
        elapsed_ms = time.ticks_diff(now, self.last)
        
        if self.rate > 0 and elapsed_ms > 0:
            add = (self.rate * elapsed_ms) // 1000
            
            if add:
                self.tokens = min(self.capacity, self.tokens + add)
                self.last = now

    async def consume(self, amount):
        if self.rate <= 0:
            return  # unlimited
        
        async with self._lock:
            while True:
                await self._refill()
                
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                
                need = amount - self.tokens
                sleep_ms = max(1, (need * 1000) // max(1, self.rate))
                await asyncio.sleep_ms(sleep_ms)

def _maybe_set(token: str):
    evt = _pending.get(token)
    
    if evt:
        try:
            evt.set()
        except Exception:
            pass

def GetMsgId():
    global _iMsgId

    result = _iMsgId
    _iMsgId += 1
    
    return result

def _make_uart(port, baud):
    # If your board needs explicit pins, wire them here:
    # return UART(port, baud, tx=UART_TX_PIN, rx=UART_RX_PIN)
    return UART(port, baud)

async def try_at_once(u, label, timeout_ms=700):
    # best-effort escape if modem was left in data mode
    try:
        u.write(b'+++')
    except: 
        pass
    await asyncio.sleep_ms(1200)
    # flush
    try:
        if u.any():
            u.read()
    except:
        pass
    # send AT and wait a bit
    try:
        u.write(b'AT\r\n')
    except:
        return False
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    buf = b''
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if u.any():
            buf += u.read() or b''
            if b'OK' in buf or b'ERROR' in buf:
                print('Autodetect: got reply on', label)
                return True
        await asyncio.sleep_ms(5)
    return False

async def autodetect_uart():
    global uart
    print('Autodetect: scanning UARTs/bauds...')
    for p in CANDIDATE_UARTS:
        for b in CANDIDATE_BAUDS:
            try:
                u = _make_uart(p, b)
                # clear and small settle delay
                try: u.read()
                except: pass
                await asyncio.sleep_ms(50)
                if await try_at_once(u, f'UART{p}@{b}'):
                    uart = u
                    print('Autodetect: USING UART', p, '@', b)
                    return True
            except Exception as ex:
                # port may not exist on this board; skip
                # print('Autodetect err:', ex)
                await asyncio.sleep_ms(10)
    print('Autodetect: no AT response on tried ports/bauds')
    return False

# -----------------------------
# Helpers
# -----------------------------
async def write_at_line(cmd):
    """Write an AT line with enforced inter-command gap and update LAST_TX_MS."""
    global uart
    
    async with cmd_lock:
        now = time.ticks_ms()
        delta = time.ticks_diff(now, _last_cmd_ms[0])
        
        if delta < INTER_CMD_GAP_MS:
            await asyncio.sleep_ms(INTER_CMD_GAP_MS - delta)
            
        uart.write(cmd + '\r\n')
        
        _last_cmd_ms[0] = time.ticks_ms()
        LAST_TX_MS[0] = _last_cmd_ms[0]

async def _drain_uart_once(timeout_ms: int):
    """Read anything available within timeout_ms (coalescing small delays)."""
    global uart
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    chunks = []
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if uart.any():
            raw = uart.read()
            if raw:
                LAST_RX_MS[0] = time.ticks_ms()
                try:
                    chunks.append(raw.decode())
                except:
                    chunks.append(raw.decode(errors='ignore'))
                await asyncio.sleep_ms(5)
        else:
            await asyncio.sleep_ms(1)
    return ''.join(chunks)

def _make_matchers(expect):
    if expect is None:
        return []
    
    if isinstance(expect, (str, bytes)):
        expect = (expect,)
        
    matchers = []
    
    for pat in expect:
        s = pat.decode() if isinstance(pat, bytes) else pat
        # heuristic: if it has regex metacharacters, treat as regex
        is_regex = any(ch in s for ch in r".^$*+?{}[]\|()")
        
        if is_regex:
            rx = re.compile(s)
            matchers.append(lambda line, _rx=rx: _rx.search(line) is not None)
        else:
            matchers.append(lambda line, _s=s: _s in line)
            
    return matchers

def _looks_final(line: str) -> bool:
    return (
        line.startswith('OK') or
        line.startswith('ERROR') or
        'FAIL' in line or
        'SEND OK' in line or
        'SEND FAIL' in line or
        'ALREADY CONNECTED' in line or
        line.startswith('link is not valid')
    )

async def _read_lines_until(expect_matchers,
                            timeout_ms: int,
                            echo: str,
                            *,
                            max_bytes: int,
                            chunk_size: int,
                            max_line_bytes: int):
    """Byte-budgeted line reader with echo filtering."""
    global uart
    
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    total = 0
    buf = ''
    last_line = ''
    echo_filtered = False
    TAIL_KEEP = max(512, max_line_bytes * 2)

    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if uart.any():
            raw = uart.read(min(chunk_size, uart.any()))
            
            if raw:
                LAST_RX_MS[0] = time.ticks_ms()
                
                try:
                    s = raw.decode()
                except:
                    s = raw.decode(errors='ignore')
                    
                total += len(s)
                buf += s
                
                if len(buf) > TAIL_KEEP:
                    buf = buf[-TAIL_KEEP:]

                if not echo_filtered and echo:
                    pos = buf.find(echo)
                    if pos != -1:
                        buf = buf[pos + len(echo):]
                        echo_filtered = True

                while True:
                    nl = buf.find('\r\n')
                    
                    if nl == -1:
                        break
                    
                    line = buf[:nl]
                    buf = buf[nl+2:]
                    
                    if len(line) > max_line_bytes:
                        line = line[:max_line_bytes]
                        
                    if not line:
                        continue
                    
                    last_line = line

                    if expect_matchers and any(m(line) for m in expect_matchers):
                        return True, (line + '\n' + buf), line
                    
                    if not expect_matchers and _looks_final(line):
                        return line.startswith('OK'), (line + '\n' + buf), line

                if total >= max_bytes:
                    return False, (last_line + '\n' + buf), last_line
        else:
            await asyncio.sleep_ms(2)

    return False, last_line, last_line

async def send_at_async(cmd: str, expect=('OK',), timeout_ms=5000) -> bool:
    """Write an AT command and await one of expected tokens from the reader loop (MicroPython-friendly).
       Uses asyncio.Event in place of Future/create_future.
    """
    async with _at_lock:
        evt = asyncio.Event()
        
        for t in expect:
            _pending[t] = evt
            
        try:
            await swriter.awrite(cmd + '\r\n')
            await asyncio.wait_for(evt.wait(), timeout_ms/1000)
            
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            for t in expect:
                _pending.pop(t, None)

async def send_at(cmd: str,
                  expect=None,
                  timeout_ms: int = 5000,
                  escape_data_mode: bool = False,
                  verbose: bool = True,
                  *,
                  max_bytes: int = SEND_AT_MAX_BYTES,
                  chunk_size: int = SEND_AT_CHUNK_SIZE,
                  max_line_bytes: int = SEND_AT_MAX_LINE):
    """Robust AT command sender."""
    # Escape from transparent data mode if requested
    if escape_data_mode and TRANSPARENT_MODE[0] and TRANSPARENT_READY[0]:
        try:
            uart.write('+++')
        except Exception as ex:
            if verbose:
                print('send_at: escape write failed:', ex)
                
        await asyncio.sleep_ms(1200)
        await _drain_uart_once(50)
        
        TRANSPARENT_READY[0] = False

    # Rate-limit: treat each AT as a "message"
    await msg_bucket.consume(1)
    await _drain_uart_once(5)

    if verbose:
        print('AT>>', cmd)
        
    await write_at_line(cmd)

    matchers = _make_matchers(expect)
    
    ok, full, last = await _read_lines_until(
        matchers, timeout_ms, echo=cmd,
        max_bytes=max_bytes, chunk_size=chunk_size, max_line_bytes=max_line_bytes
    )

    if verbose:
        if ok:
            print('AT<< OK:', last)
        else:
            reason = 'TIMEOUT/ERR'
            
            if isinstance(full, str) and len(full) >= max_bytes:
                reason = 'BYTE-BUDGET'
                
            print(f'AT<< {reason} last:', last)
    return ok

# -----------------------------
# Transparent helpers
# -----------------------------
async def reopen_transparent_stream(ip, port, verbose=True):
    """Try to escape and re-enter transparent stream cleanly."""
    global uart
    try:
        uart.write('+++')
    except Exception as ex:
        if verbose:
            print("reopen: escape write failed:", ex)
    await asyncio.sleep_ms(1200)
    await _drain_uart_once(80)

    ok = await send_at('AT', expect=('OK',), timeout_ms=2000, verbose=verbose)
    ok = ok and await send_at('AT+CIPMODE=1', expect=('OK',), timeout_ms=3000, verbose=verbose)
    ok = ok and await send_at('AT+CIPMODE?', expect=(':1',), timeout_ms=3000, verbose=verbose)
    TRANSPARENT_MODE[0] = bool(ok)

    if TRANSPARENT_MODE[0]:
        ok = await send_at('AT+CIPSTART="TCP","%s",%s' % (ip, port),
                           expect=('OK','ALREADY CONNECTED'), timeout_ms=6000, verbose=verbose)
        if not ok:
            TRANSPARENT_READY[0] = False
            return False
        ok = await send_at('AT+CIPSEND', expect=('>',), timeout_ms=4000, verbose=verbose)
        TRANSPARENT_READY[0] = bool(ok)
        return bool(ok)

    TRANSPARENT_READY[0] = False
    return False

async def start_tcp_client(ssid, pwd,
                                      ip="192.168.1.50",
                                      gw="192.168.1.1",
                                      mask="255.255.255.0",
                                      port=8080):
    # Basic sanity + disable echo
    ok = await send_at('AT', expect=('OK',), timeout_ms=1500)
    ok = ok and await send_at('ATE0', expect=('OK',), timeout_ms=1000)
    
    if not ok:
        print("AT sanity failed");
        return False

    # Station mode & join Wi-Fi
    ok = await send_at('AT+CWMODE=3', expect=('OK',), timeout_ms=1500)
    ok = ok and await send_at('AT+CWJAP="%s","%s"' % (ssid, pwd),
                              expect=('OK','ALREADY CONNECTED','FAIL'),
                              timeout_ms=20000)
    
    if not ok:
        print("CWJAP failed"); return False

    ok = await send_at('AT+CIFSR', expect=('OK',), timeout_ms=1500)
    
    ok = ok and await send_at('AT+CIPSTART="TCP","%s",%s' % (ip, port),
                              expect=('OK','ALREADY CONNECTED','ERROR'), timeout_ms=2000)
    
    if not ok:
        print("CIPSTART failed");
        return False

    ok = await send_at('AT+CIPMODE=1', expect=('OK',), timeout_ms=1500)
    
    print("TCP client connected to %s:%d" % (ip, port))
    
    return True

async def start_client(ssid, pwd, ip, port, verbose=True):
    try:
        uart.write('+++')
    except:
        pass
    
    await asyncio.sleep_ms(1200)
    await _drain_uart_once(80)  # clear any stale data

    """Bring up Wi-Fi and open TCP link; prefer transparent mode if possible."""
    steps = [
        ('AT', ('OK',)),
        ('ATE0', ('OK',)),  # disable echo
        ('AT+CWMODE=3', ('OK',)),
        ('AT+CWJAP="%s","%s"' % (ssid, pwd), ('OK','ALREADY CONNECTED','FAIL')),
        ('AT+CIFSR', ('OK',)),
        ('AT+CIPSTART="TCP","%s",%s' % (ip, port), ('OK','ALREADY CONNECTED','ERROR')),
        ('AT+CIPMODE=1', ('OK',)),
    ]
    for cmd, expect in steps:
        ok = await send_at(cmd, expect=expect, timeout_ms=20000 if 'CWJAP' in cmd else 8000, verbose=verbose)
        
        if not ok:
            if verbose:
                print('Failed step:', cmd)
                
            TRANSPARENT_MODE[0] = False
            TRANSPARENT_READY[0] = False
            
            return False
        
        await asyncio.sleep_ms(50)

    ok = await send_at('AT+CIPMODE?', expect=(':1',), timeout_ms=3000, verbose=verbose)
    TRANSPARENT_MODE[0] = bool(ok)
    
    if TRANSPARENT_MODE[0]:
        ok = await send_at('AT+CIPSEND', expect=('OK',), timeout_ms=4000, verbose=verbose)
        TRANSPARENT_READY[0] = bool(ok)
        
        if not ok and verbose:
            print('CIPSEND did not return "OK" — transparent stream not ready')
            return False
    else:
        TRANSPARENT_READY[0] = False

    return True

# -----------------------------
# Rate-limited sender
# -----------------------------
async def sender(msg_q, swriter):
    global send_sem
    print('sender start...')
    
    while True:
        msg = await msg_q.get()
        
        try:
            if isinstance(msg, tuple):
                msgId, payload = msg
            else:
                payload, msgId = msg, None

            wire_len = len(payload) + 1  # +1 for '\n'

            async with send_sem:
                await msg_bucket.consume(1)

                if TRANSPARENT_MODE[0] and TRANSPARENT_READY[0]:
                    await byte_bucket.consume(wire_len)
                    
                    print('sending payload (transparent)...', payload)
                    
                    await swriter.awrite(payload + '\n')
                    
                    LAST_TX_MS[0] = time.ticks_ms()
                    print('Send OK (transparent)')
        except Exception as ex:
            print("sender error: ", ex)

async def uart_reader_loop(recv_q, sreader):
    """Sole consumer of UART input. Splits CRLF. Routes +IPD to recv_q, resolves AT tokens."""
    global uart
    buf = b''
    print("receiver start...")    
    
    while True:
        try:
            # Read directly from UART instead of StreamReader
            if uart.any():
                chunk = uart.read()
            else:
                chunk = None
            
            if not chunk:
                await asyncio.sleep_ms(10)
                continue

            print("client received:")
            print(chunk)
            LAST_RX_MS[0] = time.ticks_ms()
            buf += chunk
            try:
                s = buf.decode()
            except:
                # Skip invalid UTF-8, keep buffer as-is for now
                await asyncio.sleep_ms(10)
                continue

            if (s.find('+IPD') >= 0):
                n1 = s.find('+IPD,')
                n2 = s.find(',',n1+5)
                ID = int(s[n1+5:n2])
                n3 = s.find(':')
                s = s[n3+1:]
                
                json_open_tag_index = s.find('{')
                json_close_tag_index = s.find('}') + 1
                
                if ((json_open_tag_index >= 0) and (json_close_tag_index > 0)):
                    s = s[json_open_tag_index:json_close_tag_index]
                    is_json = True
                
                print("Parsed data...\r\n")
                print("ID= " + str(ID) + ", Data= " + s + '\r\n' + "IsJSON= " + str(is_json))
                data_received_ok = True
                msg = ujson.loads(s)                
                await recv_q.put(msg)                
            else:
                while True:
                    i = buf.find(b'\r\n')
                    
                    if i < 0:
                        break
                    
                    line = buf[:i]
                    buf = buf[i+2:]  # drop CRLF
                    
                    print('buf: ', buf)
                    print('line: ', line)                                

                    if not line:
                        continue

                    # Debug (optional): print raw lines
                    print('[UART]', line)

                    # ---- AT token checks ----
                    if b'OK' in line:
                        _maybe_set('OK')
                        
                    if b'>' in line:
                        _maybe_set('>')
                        
                    if b'ERROR' in line:
                        _maybe_set('ERROR')
                        
                    if b'FAIL' in line:
                        _maybe_set('FAIL')
                        
                    if b'ALREADY CONNECTED' in line:
                        _maybe_set('ALREADY CONNECTED')

                    # Transparent-mode payloads: try JSON parse when braces present
                    try:
                        s_line = line.decode()
                    except:
                        # Skip lines with invalid UTF-8
                        continue

                    jstart = s_line.find('{')
                    jend = s_line.rfind('}')
                    if jstart != -1 and jend != -1 and jend > jstart:
                        try:
                            jtext = s_line[jstart:jend+1]
                            msg = ujson.loads(jtext)
                            await recv_q.put(msg)
                            print('parsed JSON:', jtext)
                        except Exception as ex:
                            try:
                                print('json parse error:', ex)
                            except:
                                pass
        except Exception as ex:
            # Avoid crashing reader; log and continue
            try:
                print('uart_reader_loop error:', ex)
            except:
                pass
            await asyncio.sleep_ms(10)

def buildTestMsg(msg_in):
    global _out_hash_md5
    
    _out_hash_md5 = uhashlib.sha256()
    
    # create a hash of the message    
    _out_hash_md5.update(msg_in)
    
    # encode the msg in base64 (strip trailing newline and decode to string)
    base64_msg = ubinascii.b2a_base64(msg_in)[:-1].decode()
    
    # encode the msg hash in base64 (strip trailing newline and decode to string)
    base64_hash_msg = ubinascii.b2a_base64(_out_hash_md5.digest())[:-1].decode()
    msgId = GetMsgId()

    msg =   {
                "Id": msgId,
                "Category": 'Test',                        
                "Base64Message":base64_msg,
                "Base64MessageHash":base64_hash_msg,
                "RspReceivedOK": False
            }
    
    msg_json = ujson.dumps(msg)
    
    return msg_json, msgId

async def testMsgGenerator(msg_q):
    print("testMsgGenerator start...")
    icounter = 1

    # Try to ensure transparent stream is ready if we intend to use it
    if TRANSPARENT_MODE[0] and not TRANSPARENT_READY[0]:
        for attempt in range(1, 4):
            print("Transparent stream not ready — attempt %d/3 to reopen..." % attempt)
            ok = await reopen_transparent_stream(IP, PORT)
            
            if ok:
                print("Transparent stream is ready (>)")
                break
            await asyncio.sleep_ms(300)
        else:
            print("Falling back to normal mode (per-message AT+CIPSEND)")
            TRANSPARENT_MODE[0] = False
            TRANSPARENT_READY[0] = False

    while icounter <= iTestMsgCount:
        msg = ("Hello World !!! %d\r\n" % icounter) * testMsgLength
        msg_json, msgId = buildTestMsg(msg)
        
        await msg_q.put((msgId, msg_json))
        
        icounter += 1
        await asyncio.sleep_ms(500)  # Increased from 50ms to 500ms

# -----------------------------
# Watchdog (optional hard reset)
# -----------------------------
async def hard_reset_modem():
    if MODEM_EN is None:
        return False
    try:
        MODEM_EN.value(0)
        await asyncio.sleep_ms(300)
        MODEM_EN.value(1)
        await asyncio.sleep_ms(1200)
        return True
    except Exception as ex:
        print("Hard reset failed:", ex)
        return False

async def link_watchdog(ip, port,
                        check_interval_ms=WATCHDOG_CHECK_MS,
                        idle_timeout_ms=WATCHDOG_IDLE_MS):
    print("Watchdog: started")
    while WATCHDOG_ENABLED[0]:
        try:
            now = time.ticks_ms()
            tx_age = time.ticks_diff(now, LAST_TX_MS[0])
            rx_age = time.ticks_diff(now, LAST_RX_MS[0])

            if tx_age < idle_timeout_ms and rx_age > idle_timeout_ms:
                print("Watchdog: link appears stuck (no RX for %d ms)" % rx_age)

                # Try to escape to command mode
                try:
                    uart.write('+++')
                except Exception as ex:
                    print("Watchdog: escape write failed:", ex)
                await asyncio.sleep_ms(1200)

                if TRANSPARENT_MODE[0]:
                    ok = await reopen_transparent_stream(ip, port)
                    if ok:
                        print("Watchdog: transparent stream restored")
                        CONSEC_FAILS[0] = 0
                        await asyncio.sleep_ms(check_interval_ms)
                        continue
                    print("Watchdog: falling back to normal mode")
                    TRANSPARENT_MODE[0] = False
                    TRANSPARENT_READY[0] = False
                    CONSEC_FAILS[0] += 1
                else:
                    ok = await send_at('AT', expect=('OK',), timeout_ms=1500)
                    if ok:
                        print("Watchdog: AT OK in normal mode")
                        CONSEC_FAILS[0] = 0
                    else:
                        print("Watchdog: normal mode AT failed")
                        CONSEC_FAILS[0] += 1

                if CONSEC_FAILS[0] >= MAX_FAILS_BEFORE_HARD:
                    print("Watchdog: escalating to hard reset…")
                    if await hard_reset_modem():
                        CONSEC_FAILS[0] = 0
                        ok = await start_client(SSID, PWD, ip, port)
                        if ok and TRANSPARENT_MODE[0]:
                            ok2 = await send_at('AT+CIPSEND', expect=('>',), timeout_ms=4000)
                            TRANSPARENT_READY[0] = bool(ok2)
                            print("Watchdog: reconnected; transparent ready =", TRANSPARENT_READY[0])
                        else:
                            print("Watchdog: reconnected in normal mode")
                    else:
                        print("Watchdog: hard reset unavailable/failed")
                        await asyncio.sleep_ms(2000)

            await asyncio.sleep_ms(check_interval_ms)

        except Exception as ex:
            print("Watchdog: exception:", ex)
            await asyncio.sleep_ms(1500)
    print("Watchdog: stopped")

# -----------------------------
# UART reader (optional console / timestamp updates)
# -----------------------------
async def uart_reader_task():
    """Simple reader that updates LAST_RX_MS and prints incoming lines (debug)."""
    line = b''
    
    while True:
        try:
            if uart and uart.any():
                b = uart.read(1)
                
                if b:
                    if b == b'\n':
                        s = line.decode(errors='ignore').strip('\r')
                        
                        if s:
                            print('<', s)
                            
                        line = b''
                        LAST_RX_MS[0] = time.ticks_ms()
                    else:
                        line += b
                        
            await asyncio.sleep_ms(1)
        except Exception as ex:
            print("uart_reader_task error:", ex)
            await asyncio.sleep_ms(50)

# -----------------------------
# Initialization
# -----------------------------
def init_uart():
    global uart, MODEM_EN, byte_bucket, msg_bucket, cmd_lock, send_sem
    
    if UART_TX_PIN is not None and UART_RX_PIN is not None:
        uart_obj = UART(UART_PORT, UART_BAUD, tx=UART_TX_PIN, rx=UART_RX_PIN)
    else:
        uart_obj = UART(UART_PORT, UART_BAUD)
    # Some firmwares benefit from larger RX buffer; uncomment if supported
    # uart_obj.init(UART_BAUD, tx=UART_TX_PIN, rx=UART_RX_PIN, rxbuf=1024)
    uart_obj.read()  # clear
    uart = uart_obj

    MODEM_EN = Pin(MODEM_EN_PIN, Pin.OUT) if MODEM_EN_PIN is not None else None

    byte_bucket = AsyncTokenBucket(BYTES_PER_SEC, BYTES_PER_SEC * 2)
    msg_bucket  = AsyncTokenBucket(MSG_PER_SEC,   MSG_PER_SEC * 2)
    cmd_lock = asyncio.Lock()
    send_sem = Semaphore(MAX_INFLIGHT_SENDS)

# -----------------------------
# Main
# -----------------------------
async def main():
    global byte_bucket, msg_bucket, cmd_lock, send_sem
    
    #init_uart()
    byte_bucket = AsyncTokenBucket(BYTES_PER_SEC, BYTES_PER_SEC * 2)
    msg_bucket  = AsyncTokenBucket(MSG_PER_SEC,   MSG_PER_SEC * 2)
    cmd_lock = asyncio.Lock()
    send_sem = Semaphore(MAX_INFLIGHT_SENDS)
    
    uart_ok = await autodetect_uart()
    
    if not uart_ok:
        print('ERROR: Could not detect modem. Check wiring/power/baud.')
        return
    
    await asyncio.sleep_ms(250)

    try:
        uart.write(b'+++')
    except:
        pass
    
    await asyncio.sleep_ms(1200)

    if (False):
        ok = await start_tcp_client(
            ssid=SSID,
            pwd=PWD,
            ip=IP,
            gw="192.168.10.1",
            mask="255.255.255.0",
            port=PORT)
    else:    
        ok = await start_client(SSID, PWD, IP, PORT)
        
    print("start_client:", ok, "transparent:", TRANSPARENT_MODE[0], "ready:", TRANSPARENT_READY[0])

    # Build a dummy StreamWriter that writes to UART directly (for awrite)
    # If you already have a proper StreamWriter, use that instead.
    class _SWriter:
        async def awrite(self, s):
            if isinstance(s, str):
                s = s.encode()
            uart.write(s)

    swriter = asyncio.StreamWriter(uart, {})
    sreader = asyncio.StreamReader(uart)
    send_q = Queue()
    recv_q = Queue()    
   
    asyncio.create_task(testMsgGenerator(send_q))    
    asyncio.create_task(sender(send_q, swriter))
    asyncio.create_task(uart_reader_loop(recv_q, sreader))
    asyncio.create_task(link_watchdog(IP, PORT))    

    # Keep the loop alive
    while True:
        await asyncio.sleep_ms(1000)

# Only run main if this file is executed as a script
if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        try:
            asyncio.new_event_loop()
        except Exception:
            pass
