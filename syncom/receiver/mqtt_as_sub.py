from mqtt_as_latest import MQTTClient, config
import uasyncio as asyncio

SERVER = '192.168.10.174'
config['server'] = SERVER

config['ssid'] = 'Cudy24G'
config['wifi_pw'] = 'ZAnne19991214'

def callback(topic, msg, retained):
    print((topic, msg, retained))

async def conn_han(client):
    await client.subscribe('file_recv', 1)
    print("Connected to broker...")

async def main(client):
    await client.connect()
    n = 0
    while True:
        await asyncio.sleep(2)
        print('publish', n)

        await client.publish('file_send', '{}'.format(n), qos = 1)
        n += 1

config['subs_cb'] = callback
config['connect_coro'] = conn_han
config['server'] = SERVER

MQTTClient.DEBUG = True  # Optional: print diagnostic messages
client = MQTTClient(config)

try:
    asyncio.run(main(client))
finally:
    client.close()  # Prevent LmacRxBlk:1 errors