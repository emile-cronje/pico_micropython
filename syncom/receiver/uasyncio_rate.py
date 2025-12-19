import uasyncio as asyncio
import gc

num_coros = (100, 200, 500, 1000, 2000)
iterations = [0, 0, 0, 0, 0]
duration = 2  # Time to run for each number of coros
count = 0
done = False

def free(full=False):
  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))

async def foo():
    global count
    while True:
        await asyncio.sleep_ms(0)
        count += 1

async def test():
    global count, done
    old_n = 0
    for n, n_coros in enumerate(num_coros):
        print('Testing {} coros for {}secs'.format(n_coros, duration))
        count = 0
        for _ in range(n_coros - old_n):
            asyncio.create_task(foo())
        old_n = n_coros
        await asyncio.sleep(duration)
        iterations[n] = count
    done = True

async def report():
    asyncio.create_task(test())
    while not done:
        await asyncio.sleep(1)
    for x, n in enumerate(num_coros):
        print('Coros {:4d}  Iterations/sec {:5d}  Duration {:3d}us iterations {:4d}'.format(
            n, int(iterations[x]/duration), int(duration*1000000/iterations[x]), iterations[x]))

async def monitorStatusQueues():
    while True:
        print("Memory status..." + free(True))
        await asyncio.sleep(1)
        
asyncio.create_task(monitorStatusQueues())        
asyncio.run(report())
