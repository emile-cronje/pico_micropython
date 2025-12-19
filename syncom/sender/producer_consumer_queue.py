import uasyncio as asyncio
from machine import Pin
from queue import Queue
from btree import BTree
import time, gc

event_test = asyncio.Event()
bt = BTree(3, 'btree_data.json')  # Create a B-tree with a minimum degree of 3 and specify a storage file

async def produce(queue):
    icount = 0

    while True:
        await queue.put(str(icount))  # Put result on queue        
        icount += 1
        await asyncio.sleep(.02)

async def consume(queue):
    while True:
        await event_test.wait()

        while (queue.qsize() > 5):
            item = await queue.get()  # Blocks until data is ready            
            #print("Pulled item..." + str(item))
            key = time.time_ns()
            bt.insert(key, item)            
            await asyncio.sleep(.01)

        event_test.clear()

async def watchQueue(queue):
    while True:
        if (queue.qsize() > 10):
            event_test.set()

        await asyncio.sleep(1)

async def showQueueLength(queue):
    while True:
        print("Queue length..." + str(queue.qsize()))
        await asyncio.sleep(2)

def free(full=True):
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  #else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))
  else : return ('Free:{0}'.format(P))  

async def showMemUsage():
    while True:
        print(free(True))        
        await asyncio.sleep(4)

async def heartbeat():
    led = Pin(25, Pin.OUT)
    while True:
        await asyncio.sleep_ms(500)
        led(not led())

async def main():
    queue = Queue()    
    asyncio.create_task(produce(queue))            
    asyncio.create_task(consume(queue))                
    asyncio.create_task(watchQueue(queue))                    
    asyncio.create_task(showQueueLength(queue))
    asyncio.create_task(showMemUsage())        
    asyncio.run(heartbeat())            

    print('Tasks are running...')
    while True:
        await asyncio.sleep(5)

asyncio.run(main())
