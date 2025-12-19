import machine
import gc
import uasyncio as asyncio
import os
import time
from ramblock import RAMBlockDevExt

entityCount = 50
threadCount = 8
finalResult = True
rbDir = '/rb'

async def sdtest(id, targetDir, mustDelete = False):
    global finalResult
    
    log(os.listdir(targetDir))
    files = os.listdir(targetDir)
    counter = 0
    
    for count in range(entityCount):
        counter += 1
        s = "Thread: " + str(id) + " Count: " + str(count + 1)
        print(s)
            
        line = 'abcdefghijklmnopqrstuvwxyz_' + str(id + count) + '\n'
        lines = line * count
        short = '1234567890\n'

        if (targetDir == ''):
            fn = 'rats_long_' + str(id) + '.txt'
        else:
            fn = targetDir + '/rats_long_' + str(id) + '.txt'
            
        log('Multiple block read/write')
        
        with open(fn,'w') as f:
            n = f.write(lines)
            log(str(n) + ' bytes written')
            n = f.write(short)
            log(str(n) + ' bytes written')
            n = f.write(lines)
            log(str(n) + ' bytes written')

        with open(fn,'r') as f:
            result_long = f.read()
            log(str(len(result_long)) + ' bytes read')

        if (targetDir == ''):
            fn = 'rats_short_' + str(id) + '.txt'
        else:
            fn = targetDir + '/rats_short_' + str(id) + '.txt'
            
        log('Single block read/write')
        
        with open(fn,'w') as f:
            n = f.write(short) # one block
            log(str(n) + ' bytes written')

        with open(fn,'r') as f:
            result_short = f.read()
            log(str(len(result_short)) + ' bytes read')

        log('Verifying data read back')
        success = True
        
        if result_long == ''.join((lines, short, lines)):
            log('Large file Pass')
        else:
            log('Large file Fail')
            success = False
            
        if result_short == short:
            log('Small file Pass')
        else:
            log('Small file Fail')
            success = False
            
        await asyncio.sleep(.05)            

    if (success == True):
        success = counter == (entityCount)
    
    if (success == False):
        finalResult = False
        return
        
    print('Tests', 'passed' if success else 'failed', str(id))

def free(full=True):
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  #else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))
  else : return ('Free:{0}'.format(P))  

def rm(d):  # Remove file or tree
    try:
        #print(os.stat(d))
        
        if os.stat(d)[0] & 0x4000:  # Dir
            for f in os.ilistdir(d):
                if f[0] not in ('.', '..'):
                    rm("/".join((d, f[0])))  # File or Dir
            os.rmdir(d)
        else:  # File
            os.remove(d)
    except:
        print("rm of '%s' failed" % d)
        
def log(s):
    return
    print(s)
    
async def showMemUsage():
    while True:
        print(free(True))        
        await asyncio.sleep(5)
    
async def main():
    tasks = []
    start = time.time()
    ramBefore = free(True)    
    
    for id in range(threadCount):    
        task = asyncio.create_task(sdtest(id, rbDir, True))        
        tasks.append(task)

    asyncio.create_task(showMemUsage())    
    print('Tasks are running...')

    await asyncio.gather(*tasks)
    
    end = time.time()    
    print(end - start)
    print('seconds')
    
    print('All Tests', 'passed' if finalResult else 'failed')    
    
    ramAfter = free(True)
    print("before:", ramBefore)
    print("after:", ramAfter)
    
bdev = RAMBlockDevExt(512, 200)
os.VfsFat.mkfs(bdev)
os.mount(bdev, rbDir)

asyncio.run(main())