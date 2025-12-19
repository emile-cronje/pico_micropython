# pico_simple.py Minimal publish/subscribe test program for Pyboard MQTT bridge

# Author: Peter Hinch.
# Copyright Peter Hinch 2017-2021 Released under the MIT license.

# Host is assumed to have no LED's. Output is via console.
# From PC issue (for example)
# Turn the Pyboard green LED on (or off):
# mosquitto_pub -h 192.168.0.10 -t green -m on
# Print publications from the Pyboard:
# mosquitto_sub -h 192.168.0.10 -t result

import utime,time
from ubinascii import hexlify
import ubinascii
import uhashlib
import ujson
import os
import uasyncio as asyncio
from pbmqtt import MQTTlink
import hw_pico as hardware  # Pin definitions. Heartbeat on Pico LED.
import net_local  # WiFi credentials

qos = 1

def buildMsg(msg_in):
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
    
    return ujson.dumps(msg)

async def publish(mqtt_link):
    count = 1
    
    while True:
        msgToSend = buildMsg(str(count))
        
        await mqtt_link.publish('pico_simple_topic', msgToSend, False, qos)
        
        print("published..." + msgToSend)                
        count += 1
        await asyncio.sleep(1)

def cbpico(topic, msg, retained):
    print(topic, msg)

def cbnet(state, _):  # Show WiFi state. Discard mqtt_link arg.
    print('cbnet: network is ', 'up' if state else 'down')

async def main(mqtt_link):
    asyncio.create_task(mqtt_link.subscribe('pico_mqtt', qos, cbpico))
    asyncio.create_task(publish(mqtt_link))
    print("main running...")
    
    while True:
        await asyncio.sleep(10)

MQTTlink.will('result', 'simple client died')
mqtt_link = MQTTlink(hardware.d, net_local.d, wifi_handler=(cbnet,()), verbose=True)

try:
    asyncio.run(main(mqtt_link))
finally:
    asyncio.new_event_loop()
