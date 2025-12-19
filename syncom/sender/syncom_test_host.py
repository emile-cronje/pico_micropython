import utime,time
from ubinascii import hexlify
import ubinascii
import uhashlib
import ujson
import os
import uasyncio as asyncio
from syncom_orig import SynCom
from machine import Pin

string_mode = False
SEP = chr(127)

async def passive_task(chan):
    while True:
        obj = await chan.await_obj()
        chan.send(obj)

def argformat(*a):
    return SEP.join(['{}' for x in range(len(a))]).format(*a)

async def main_task(chan):
    icounter = 0
    
    while True:
        #sendstr = 'Hello World !!! ' + str(icounter) + " : " + str(taskId) + '\r\n'
        #sendstr = 'Hello World !!! ' + str(icounter) + str(taskId) + '\r\n'
        sendstr = argformat(icounter, 'result')        
        
        if (string_mode == True):          
            chan.send(sendstr)
        else:            
            sendMsg(sendstr, chan)
        
        icounter += 1
        await asyncio.sleep_ms(1000)
        obj = await chan.await_obj()
        print("received..." + str(obj))

async def heartbeat(led):
    while True:
        await asyncio.sleep_ms(500)
        led(not led())

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
    print("sent..." + msg_in)            

mtx = Pin(17, Pin.OUT, value = 0)    # Define pins
mckout = Pin(18, Pin.OUT, value = 0) # clock must be initialised to zero.
mrx = Pin(19, Pin.IN)
mckin = Pin(20, Pin.IN)
reset = Pin(16, Pin.OPEN_DRAIN)

channel = SynCom(False, mckin, mckout, mrx, mtx, string_mode = string_mode, timeout = 2000)#, pin_reset = None)
led = Pin(25, Pin.OUT)

try:
    asyncio.create_task(channel.start(main_task))                
    asyncio.run(heartbeat(led))    
except KeyboardInterrupt:
    pass
finally:
    mckout(0)  # For a subsequent run
    _ = asyncio.new_event_loop()
    