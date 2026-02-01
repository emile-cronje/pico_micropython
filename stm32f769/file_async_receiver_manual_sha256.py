from mqtt_as_latest import MQTTClient, config
import uasyncio as asyncio
import gc
import ujson
import uhashlib
import ubinascii
import machine
import os, uos
import time
from machine import SPI, Pin
from queue import Queue

SERVER_1 = '192.168.10.174'
SERVER_2 = '192.168.10.135'
SERVER_3 = '192.168.10.124'

_error_q = {}
_success_q = {}
_send_q = Queue()
_in_hash_md5 = uhashlib.sha256()
fout = None
backupDir = '/sd/backups_new'

async def conn_han(client):
    await client.subscribe('rp6502_pub_1', 1)

def sha256_simple(input_data):
    """
    Simplified *custom checksum* implementation (matches C version).
    Returns Base64-encoded 32-byte hash using ubinascii.
    
    NOTE: This is NOT the standard cryptographic SHA256 algorithm.
    """
    if isinstance(input_data, str):
        # MicroPython uses 'utf8' or 'utf-8'
        input_data = input_data.encode('utf8')
    
    input_len = len(input_data)
    # Use standard uctypes or struct module for C-like 32-bit operations 
    # or ensure Python's default large integers don't cause issues.
    # & 0xFFFFFFFF ensures 32-bit wrap-around behavior.
    sum_val = 0x5A5A5A5A & 0xFFFFFFFF 
    
    # --- Custom Checksum Logic ---
    
    # Mix all input bytes
    for i in range(input_len):
        sum_val = (((sum_val << 5) + sum_val) + input_data[i]) & 0xFFFFFFFF
        sum_val = (sum_val ^ (sum_val >> 16)) & 0xFFFFFFFF
    
    # Generate 32 bytes of "hash" from the checksum
    hash_bytes = bytearray(32)
    for i in range(32):
        hash_bytes[i] = (sum_val >> ((i % 4) * 8)) & 0xFF
        if i % 4 == 3:
            # Note: This line uses 'input_data[i % input_len]' which can cause an 
            # IndexError if i > input_len, but the custom logic seems to rely on this.
            sum_val = (((sum_val << 7) ^ (sum_val >> 11)) + input_data[i % input_len]) & 0xFFFFFFFF
            
    # --- Base64 Encoding Fix ---
    
    # Base64 encode the hash using ubinascii.b2a_base64
    # ubinascii.b2a_base64 returns bytes which usually includes a trailing newline.
    b64_encoded_bytes = ubinascii.b2a_base64(hash_bytes)
    
    # Decode the resulting bytes to a string and strip the trailing newline (\n)
    return b64_encoded_bytes.decode('utf8').strip()

def callback(topic, msg_in, retained):
    global _success_q, _error_q
    print("Callback: " + str((topic, msg_in, retained)))
    msg = ujson.loads(msg_in)
    
    if ("Category" in msg.keys()):
        category = msg["Category"]
    
        if (category == 'Files'):
            step = msg["Step"]
            
            if (step == 'Start'):
                print("starting sync...")
                _success_q.clear()
                _error_q.clear()
            else:
                print("processing file...")                
                processFile(msg, _success_q, _error_q)
                
        if (category == 'Test'):
            message = msg["Message"]
            #print("Test: " + str(msg))
            handleTestMessage(msg)

def handleTestMessage(msg):
    try:
        msg_id = msg.get('Id')
        b64_in = msg.get('Base64Message', '')
        b64_hash_in = msg.get('Base64MessageHash', '')
        guid = msg.get('Guid', '')        
        
        # Decode Base64 message and hash
        clear = ubinascii.a2b_base64(b64_in) if isinstance(b64_in, str) else b64_in
        
        # Compute hash using sha256_simple (matches C implementation)
        calc_hash = sha256_simple(clear)
        
        # Compare hashes
        if calc_hash != b64_hash_in:
            err = 'test msg hash diff'
            print(err)
            print('b64_in: ' + str(b64_in))
            print('b64_hash_in (received): ' + str(b64_hash_in))
            print('b64_hash_in (calculated): ' + str(calc_hash))
        else:
            print("Hash Matched OK: " + str(clear))
        
        # Generate response with same hash function
        rsp_hash = sha256_simple(clear)
        b64_rsp = ubinascii.b2a_base64(clear)[:-1].decode('utf-8')
        
        rsp = {
               'Id': msg_id,
               'Category': 'Test',
               'Base64Message': b64_rsp,
               'Base64MessageHash': rsp_hash,
               'RspReceivedOK': True,
               'Guid': guid
        }
        
        _send_q.put_nowait(ujson.dumps(rsp))
        print(f'Queued response for Id={msg_id}')
    except Exception as ex:
        print('Test handler error: %s' % ex)        
        #error_q.append('Test handler error: %s' % ex)
    
def processFile(msg, success_q, error_q):
    global _in_hash_md5, fout
   
    print("process file...")
    step = msg["Step"]
    #print("Msg: " + str(msg))
    
    if (step == "Header"):
        print("Processing header...")        
        _in_hash_md5 = uhashlib.sha256()              
        file_name = msg["FileName"]            
        file_out = backupDir + "/copy-" + file_name
        print("creating file: " + file_out)        
        fout = open(file_out, "wb")
        print("created file: " + file_out)
        success_q[file_name] = 'File copy starting...'

        if (file_name in error_q.keys()):
            del error_q[file_name]

    elif (step == "Content"):
        print("Processing content...")                
        file_name = msg["FileName"]                            
        file_data = ubinascii.a2b_base64(msg["FileData"])
        _in_hash_md5.update(file_data)
        progress = msg["ProgressPercentage"]                                    
        success_q[file_name] = 'File copy in progress...' + str(progress) + '%'
        
        if (fout != None):
            fout.write(file_data)

    elif (step == "End"):
        print("Processing end...")
        file_name = msg["FileName"]                        
        in_hash_final = _in_hash_md5.digest()
        base64_hash_data = ubinascii.b2a_base64(in_hash_final)[:-1]
        base64_hash_data_string = base64_hash_data.decode("utf-8")
        in_msg_hash = msg["HashData"]
        
        if (base64_hash_data_string == in_msg_hash):
            success_q[file_name] = "File copy OK"
        else:
            error_q[file_name] = "File copy failed"
            print("msg hash:" + in_msg_hash)
            print("file hash:" + base64_hash_data_string)            
    
def file_exist(filename):
    try:
        f = open(filename, "r")
        exists = True
        f.close()
    except OSError:
        exists = False
    return exists        
    
async def main():
    n = 0
    
    while True:
        await asyncio.sleep(2)
        n += 1

def free(full=False):
#  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))

def dir_exists(path):
    try:
        f = os.listdir(path)
        
        if f != []:
            return True
        else:
            return False
    except OSError:
        return False

async def monitorStatusQueues(success_q, error_q):
    while True:
        print("Error Queue length..." + str(len(error_q)))
        print("Success Queue length..." + str(len(success_q)))        

        for key, value in success_q.items():
            print(key, ' : ', value)

        for key, value in error_q.items():
            print(key, ' : ', value)

        print("Memory status..." + free(True))
        print("Time..." + str(time.gmtime()))                
        await asyncio.sleep(3)

async def monitorSendQueue(mqtt_clients, send_q):
    for j in range(len(mqtt_clients)):    
        await mqtt_clients[j].connect()
        
    i = 0
    
    while True:
        msg = await send_q.get()
 
        if (i % 2) == 0:
            await mqtt_clients[0].publish('rp6502_sub_1', msg, qos = 1)
        else:            
            await mqtt_clients[0].publish('rp6502_sub_1', msg, qos = 1)

        print("Published to server 1:")
        print(str(msg))
        i += 1
        await asyncio.sleep(.5)

def clockTest():
    clock = AClock()
    clock.run()

config['subs_cb'] = callback
config['connect_coro'] = conn_han
config['server'] = SERVER_1

MQTTClient.DEBUG = True
client_1 = MQTTClient(config)

mqtt_clients = []
mqtt_clients.append(client_1)

try:
#    asyncio.create_task(monitorStatusQueues(_success_q, _error_q))
    asyncio.create_task(monitorSendQueue(mqtt_clients, _send_q))
    asyncio.run(main())
finally:
    client_1.close()
