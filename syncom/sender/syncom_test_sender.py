import utime,time
from ubinascii import hexlify
import ubinascii
import uhashlib
import ujson
import os
import uasyncio as asyncio
from syncom_orig import SynCom
from machine import Pin
import gc

SEP = chr(127)
string_mode = False
led = Pin(25, Pin.OUT)

async def heartbeat(led):
    while True:
        await asyncio.sleep_ms(500)
        led(not led())

def argformat(*a):
    return SEP.join(['{}' for x in range(len(a))]).format(*a)

async def main_task(chan):
    icounter = 0
    print("running active task...")

    while True:
        sendstr = 'Hello Pico 2W World !!! ' + str(icounter) + '\r\n'
        
        if (string_mode == True):          
            chan.send(sendstr)
        else:            
            sendMsg(sendstr, chan)
            
        icounter += 1
       
        if ((icounter % 5) == 0):
            print(free(True))
            
        recv = await chan.await_obj()
        
        print("Received: " + str(recv))
        
#        decodedMsg = decodeMessage(recv)
        decodedMsg = recv

        print("decodedMsg: " + str(decodedMsg))
        
        if (decodedMsg != sendstr):
            print("mismatch!!")
            print("Sent: " + sendstr)
            print("Received: " + str(recv))            
        else:
            print("matched..." + str(recv))
            
        await asyncio.sleep_ms(1000)            

def free(full=False):
#  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))
  
def sendMsg(msg_in, chan):
    out_hash_md5 = uhashlib.sha256()
    
    # create a hash of the message    
    out_hash_md5.update(msg_in)
    
    # encode the msg in base64
    base64_msg = ubinascii.b2a_base64(msg_in)
    
    # encode the msg hash in base64    
    base64_hash_msg = ubinascii.b2a_base64(out_hash_md5.digest())[:-1]
    
    msg =   {
                "Message":msg_in,        
                "Base64Message":base64_msg,
                "Base64MessageHash":base64_hash_msg
            }
    chan.send(msg)
    print("sent..." + str(msg))            

def decodeMessage(msg):
    base64message = msg["Base64Message"]
    base64messagehash = msg["Base64MessageHash"]
    print("base64message: " + base64message)
    print("base64messagehash: " + base64messagehash)    
    msg = ubinascii.a2b_base64(base64message)
    
    return msg

reset = Pin(16, Pin.OPEN_DRAIN)
dout = Pin(17, Pin.OUT, value = 0)    # Define pins
ckout = Pin(18, Pin.OUT, value = 0) # clock must be initialised to zero.
din = Pin(19, Pin.IN)
ckin = Pin(20, Pin.IN)

channel = SynCom(False, ckin, ckout, din, dout, string_mode = string_mode, timeout = 2000, pin_reset = None)
led = Pin(25, Pin.OUT)

try:
    asyncio.create_task(channel.start(main_task))
    asyncio.run(heartbeat(led))    
except KeyboardInterrupt:
    pass
finally:
    ckout(0)  # For a subsequent run
    _ = asyncio.new_event_loop()
    