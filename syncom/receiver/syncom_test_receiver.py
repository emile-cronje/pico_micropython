import uasyncio as asyncio
from syncom_orig import SynCom
from machine import Pin
import utime,time
import ujson
import ubinascii
import uhashlib
import gc
import machine

SEP = chr(127)
string_mode = False
led = machine.Pin(25, machine.Pin.OUT)

 # Task just echoes objects back
async def passive_task(chan):
    icounter = 0
    
    while True:
        obj = await chan.await_obj()
        
        if (obj == None):
            print("None received...")
            continue
        
        #ilst = obj.split(SEP)
        #print("passive received...1" + ilst[0])
        #print("passive received...2" + ilst[1])                
        print("passive received..." + str(obj))
        
        if (string_mode == True):
            rsp = obj
        else:                
            rsp = await processMsg(obj)

        chan.send(rsp)
        print("passive sent..." + str(rsp))
        
        icounter += 1
       
        if ((icounter % 5) == 0):
            print(free(True))

async def processMsg(msg):
    if (msg == None):
        return
    
    print("Process msg..." + str(msg))                    
    
    msg = decodeMessage(msg)
#    msg = encodeMessage(msg)    
    
    return msg
    
def decodeMessage(msg):
    base64message = msg["Base64Message"]
    base64messagehash = msg["Base64MessageHash"]
    print("base64message: " + base64message)
    print("base64messagehash: " + base64messagehash)    
    msg = ubinascii.a2b_base64(base64message)
    
    return msg

def encodeMessage(msg):
    out_hash_md5 = uhashlib.sha256()
    
    # create a hash of the message    
    out_hash_md5.update(msg)
    
    # encode the msg in base64
    base64_msg = ubinascii.b2a_base64(msg)
    
    # encode the msg hash in base64    
    base64_hash_msg = ubinascii.b2a_base64(out_hash_md5.digest())[:-1]
    
    msg =   {
                "Message":msg,        
                "Base64Message":base64_msg,
                "Base64MessageHash":base64_hash_msg
            }

    return msg


async def heartbeat(led):
    while True:
        await asyncio.sleep_ms(500)
        led(not led())
    
def free(full=False):
  #gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))

dout = Pin(14, Pin.OUT, value = 0)    # Define pins
ckout = Pin(15, Pin.OUT, value = 0) # clock must be initialised to zero.
din = Pin(13, Pin.IN)
ckin = Pin(12, Pin.IN)

channel = SynCom(True, ckin, ckout, din, dout, string_mode = string_mode)

try:
    asyncio.run(channel.start(passive_task))
    asyncio.run(heartbeat(led))    
except KeyboardInterrupt:
    pass
finally:
    ckout(0)  # For a subsequent run
    _ = asyncio.new_event_loop()