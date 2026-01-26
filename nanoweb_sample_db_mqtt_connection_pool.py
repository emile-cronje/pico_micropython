import json
import os
import time
import sys
import uasyncio as asyncio
import gc
from nanoweb import HttpError, Nanoweb, send_file
from ubinascii import a2b_base64 as base64_decode
import uhashlib
import ubinascii
import machine
from ToDoController import ToDoController
from AssetController import AssetController
from MeterController import MeterController
from MeterReadingController import MeterReadingController
from AssetTaskController import AssetTaskController
from mqtt_as_latest import MQTTClient, config
import uhashlib
from ramblock import RAMBlockDevExt

useMem = True
useRAMDisk = False
useSDDisk = False

#mem cache
if ((useMem == True) & (useRAMDisk == False)):
    from btree_custom_mem import BTree
    from ToDoDaoBTCustomMem import ToDoDaoBT
    from AssetDaoBTCustomMem import AssetDaoBT
    from AssetTaskDaoBTCustomMem import AssetTaskDaoBT
    from MeterDaoBTCustomMem import MeterDaoBT
    from MeterReadingDaoBTCustomMem import MeterReadingDaoBT
elif ((useMem == False) & ((useRAMDisk == True) | (useSDDisk == True))):
    #from btree_disk import BTree
    from bplus_tree import BPlusTree as BTree    
    from ToDoDaoBTCustomMem import ToDoDaoBT
    from AssetDaoBTCustomMem import AssetDaoBT
    from AssetTaskDaoBTCustomMem import AssetTaskDaoBT
    from MeterDaoBTCustomMem import MeterDaoBT
    from MeterReadingDaoBTCustomMem import MeterReadingDaoBT
else:
#disk cache
    from ToDoDaoBTCustomDiskCache import ToDoDaoBT
    from AssetDaoBTCustomDiskCache import AssetDaoBT
    from AssetTaskDaoBTCustomDiskCache import AssetTaskDaoBT
    from MeterDaoBTCustomDiskCache import MeterDaoBT
    from MeterReadingDaoBTCustomDiskCache import MeterReadingDaoBT

from MqttConnectionPool import MqttConnectionPool
import pyb

_treeDepth = 5
CREDENTIALS = ('foo', 'bar')
EXAMPLE_ASSETS_DIR = './example-assets/'
MQTT_BROKERS = ['192.168.10.124', '192.168.10.135', '192.168.10.174']
#MQTT_BROKERS = ['192.168.10.174']
sdDir = "/sd"
rbDir = "/rb"

toDoController = None
assetController = None
meterController = None
dbName = None
toDoDao = None
assetDao = None
meterDao = None
_error_q = {}
_success_q = {}
_in_hash_md5 = uhashlib.sha256()
fout = None

async def Init(backupDir):
    global toDoController
    global assetController
    global meterController
    global meterReadingController        
    global assetTaskController    
    global dbName

    if ((useMem == True) | (useRAMDisk == True) | (useSDDisk == True)):
        if ((useRAMDisk == True) | (useSDDisk == True)):
            toDoDir = backupDir + "/todo"
            toDoBTree = BTree(_treeDepth, toDoDir, 'toDo.json')
            
            assetDir = backupDir + "/asset"
            assetBTree = BTree(_treeDepth, assetDir, 'asset.json')
            
            assetTaskDir = backupDir + "/assetTask"            
            assetTaskBTree = BTree(_treeDepth, assetTaskDir, 'assetTask.json')
            
            meterDir = backupDir + "/meter"                        
            meterBTree = BTree(_treeDepth, meterDir, 'meter.json')
            
            meterReadingDir = backupDir + "/meterReading"                                    
            meterReadingBTree = BTree(_treeDepth, meterReadingDir, 'meterReading.json')
        elif (useMem == True):            
            toDoBTree = BTree(_treeDepth)
            assetBTree = BTree(_treeDepth)
            assetTaskBTree = BTree(_treeDepth)
            meterBTree = BTree(_treeDepth)
            meterReadingBTree = BTree(_treeDepth)
        
        toDoDao = ToDoDaoBT(toDoBTree)
        assetDao = AssetDaoBT(assetBTree)
        meterDao = MeterDaoBT(meterBTree)
        meterReadingDao = MeterReadingDaoBT(meterReadingBTree, meterDao)                        
        assetTaskDao = AssetTaskDaoBT(assetTaskBTree, assetDao)
    else:
        toDoDao = ToDoDaoBT(_treeDepth, backupDir)
        assetDao = AssetDaoBT(_treeDepth, backupDir)
        assetTaskDao = AssetTaskDaoBT(_treeDepth, backupDir)                                                
        meterDao = MeterDaoBT(_treeDepth, backupDir)
        meterReadingDao = MeterReadingDaoBT(_treeDepth, backupDir)                        
        
    topics = ['/entities']
    mqttConnectionPool = MqttConnectionPool(MQTT_BROKERS)
    await mqttConnectionPool.Initialise()
    toDoController = ToDoController(mqttConnectionPool, toDoDao, topics)
    assetTaskController = AssetTaskController(mqttConnectionPool, assetTaskDao, topics)        
    assetController = AssetController(mqttConnectionPool, assetDao, topics, assetTaskController)
    meterReadingController = MeterReadingController(mqttConnectionPool, meterReadingDao, topics)            
    meterController = MeterController(mqttConnectionPool, meterDao, topics, meterReadingController)

async def get_time():
    uptime_s = int(time.ticks_ms() / 1000)
    uptime_h = int(uptime_s / 3600)
    uptime_m = int(uptime_s / 60)
    uptime_m = uptime_m % 60
    uptime_s = uptime_s % 60
    freemem = free(True)
    itemCount = await toDoController.GetItemCount()
    assetCount = await assetController.GetAssetCount()    
    return (
        '{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*time.localtime()),
        '{:02d}h {:02d}:{:02d}'.format(uptime_h, uptime_m, uptime_s),
        free(True), itemCount, assetCount)

async def api_send_response(request, code=200, message="OK"):
    await request.write("HTTP/1.1 %i %s\r\n" % (code, message))
    await request.write("Content-Type: application/json\r\n\r\n")
    await request.write('{"status": true}')

def authenticate(credentials):
    async def fail(request):
        await request.write("HTTP/1.1 401 Unauthorized\r\n")
        await request.write('WWW-Authenticate: Basic realm="Restricted"\r\n\r\n')
        await request.write("<h1>Unauthorized</h1>")

    def decorator(func):
        async def wrapper(request):
            header = request.headers.get('Authorization', None)
            if header is None:
                print("Auth: no header")
                return await fail(request)

            # Authorization: Basic XXX
            kind, authorization = header.strip().split(' ', 1)
            if kind != "Basic":
                print("Auth: Non-basic auth")                
                return await fail(request)

            authorization = base64_decode(authorization.strip()) \
                .decode('ascii') \
                .split(':')

            if list(credentials) != list(authorization):
                print("Auth: Credentials invalid")                                
                return await fail(request)

            return await func(request)
        return wrapper
    return decorator

@authenticate(credentials=CREDENTIALS)
async def api_status(request):
    """API status endpoint"""
    await request.write("HTTP/1.1 200 OK\r\n")
    await request.write("Content-Type: application/json\r\n\r\n")

    time_str, uptime_str, free_mem, item_count, asset_count = await get_time()
    await request.write(json.dumps({
        "time": time_str,
        "uptime": uptime_str,
        "freemem": free_mem,
        "item_count": item_count,
        "asset_count": asset_count,        
        'python': '{} {} {}'.format(
            sys.implementation.name,
            '.'.join(
                str(s) for s in sys.implementation.version
            ),
            sys.implementation._mpy
        ),
        'platform': str(sys.platform),
    }))


@authenticate(credentials=CREDENTIALS)
async def api_ls(request):
    await request.write("HTTP/1.1 200 OK\r\n")
    await request.write("Content-Type: application/json\r\n\r\n")
    await request.write('{"files": [%s]}' % ', '.join(
        '"' + f + '"' for f in sorted(os.listdir('.'))
    ))

@authenticate(credentials=CREDENTIALS)
async def api_download(request):
    await request.write("HTTP/1.1 200 OK\r\n")
    filename = request.url[len(request.route.rstrip("*")) - 1:].strip("/")        
    await request.write("Content-Type: application/octet-stream\r\n")
    await request.write("Content-Disposition: attachment; filename=%s\r\n\r\n"
                        % filename)
    await send_file(request, filename)

@authenticate(credentials=CREDENTIALS)
async def api_download_all(request):
    await request.write("HTTP/1.1 200 OK\r\n")
    print("api_download_all...")    

    filenames = []
    
    for filename in os.listdir():
        if (filename != 'example-assets'):
            filenames.append(filename)        

    for i in range(0, len(filenames)):
        filename = filenames[i]
        print("filename:" + filename)
        await request.write("Content-Type: application/octet-stream\r\n")
        await request.write("Content-Disposition: attachment; filename=%s\r\n\r\n"
                            % filename)
        await send_file(request, filename)

@authenticate(credentials=CREDENTIALS)
async def api_delete(request):
    if request.method != "DELETE":
        raise HttpError(request, 501, "Not Implemented")

    filename = request.url[len(request.route.rstrip("*")) - 1:].strip("\/")

    try:
        os.remove(filename)
    except OSError as e:
        raise HttpError(request, 500, "Internal error")

    await api_send_response(request)


@authenticate(credentials=CREDENTIALS)
async def upload(request):
    if request.method != "PUT":
        raise HttpError(request, 501, "Not Implemented")

    bytesleft = int(request.headers.get('Content-Length', 0))

    if not bytesleft:
        await request.write("HTTP/1.1 204 No Content\r\n\r\n")
        return

    output_file = request.url[len(request.route.rstrip("*")) - 1:].strip("\/")
    tmp_file = output_file + '.tmp'

    try:
        with open(tmp_file, 'wb') as o:
            while bytesleft > 0:
                chunk = await request.read(min(bytesleft, 64))
                o.write(chunk)
                bytesleft -= len(chunk)
            o.flush()
    except OSError as e:
        raise HttpError(request, 500, "Internal error")

    try:
        os.remove(output_file)
    except OSError as e:
        pass

    try:
        os.rename(tmp_file, output_file)
    except OSError as e:
        raise HttpError(request, 500, "Internal error")

    await api_send_response(request, 201, "Created")


@authenticate(credentials=CREDENTIALS)
async def file_assets(request):
    await request.write("HTTP/1.1 200 OK\r\n")

    args = {}

    filename = request.url.split('/')[-1]
    if filename.endswith('.png'):
        args = {'binary': True}

    await request.write("\r\n")

    await send_file(
        request,
        './%s/%s' % (EXAMPLE_ASSETS_DIR, filename),
        **args,
    )


@authenticate(credentials=CREDENTIALS)
async def index(request):
    await request.write(b"HTTP/1.1 200 Ok\r\n\r\n")

    await send_file(
        request,
        './%s/index.html' % EXAMPLE_ASSETS_DIR,
    )

@authenticate(credentials=CREDENTIALS)
async def todo_items(request):
    payload = request.body
    dataKey = "itemData"
    result = "{}"
    
    if request.method == "POST":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            item = json.loads(payload[dataKey])
            result = await toDoController.AddItem(payload["mqttSessionId"], item)
        
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))
    elif request.method == "GET":
        urlParts = request.url.split('/')
        id = urlParts[3]        

        # Return all items
        if (id == ""):
            result = await toDoController.GetAllItems()
        elif (id == "count"):
            result = await toDoController.GetItemCount()
            print("item count..." + str(result))            
        else:            
            id = id.replace("%22", "'")
            result = await toDoController.GetItemById(id, True)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "PUT":
        urlParts = request.url.split('/')
        #print("len urlparts = " + str(len(urlParts)))
        #print("url = " + request.url)
        id = urlParts[3]
        
        if (dataKey in payload):        
            item = json.loads(payload[dataKey])        
            result = await toDoController.UpdateItem(payload["mqttSessionId"], id, item)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
        #print("api: done update item...: " + json.dumps(result))                        
    elif request.method == "DELETE":
        urlParts = request.url.split('/')
        id = ''
        
        print("len: " + str(len(urlParts)))
        
        if (len(urlParts) == 4):         
            id = urlParts[3]

        print("api: delete item...id: " + str(id))
        
        if (id == ''):
            result = await toDoController.DeleteAllItems()
        else:
            result = await toDoController.DeleteItem(payload["mqttSessionId"], id, payload["messageId"])
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))
    else:
        raise HttpError(request, 501, "Not Implemented")

@authenticate(credentials=CREDENTIALS)
async def assets(request):
    payload = request.body
    dataKey = "assetData"
    result = "{}"
    
    if request.method == "POST":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            asset = json.loads(payload[dataKey])        
            result = await assetController.AddAsset(payload["mqttSessionId"], asset)
        
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))        
    elif request.method == "GET":
        urlParts = request.url.split('/')
        id = urlParts[3]                

        # Return all assets
        if (id == ""):
            result = await assetController.GetAllAssets()
        elif (id == "count"):
            result = await assetController.GetAssetCount()
            print("asset count..." + str(result))                        
        else:            
            id = id.replace("%22", "'")
            result = await assetController.GetAssetById(id, True)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "PUT":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):
            id = urlParts[3]            
            asset = json.loads(payload[dataKey])        
            result = await assetController.UpdateAsset(payload["mqttSessionId"], id, asset)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
  #      print("api: done update asset...: " + json.dumps(result))                        
    elif request.method == "DELETE":
        urlParts = request.url.split('/')
        id = ''
        
        if (len(urlParts) == 4):         
            id = urlParts[3]

        if (id == ''):
            result = await assetController.DeleteAllAssets()
        else:
            result = await assetController.DeleteAsset(payload["mqttSessionId"], id, payload["messageId"])
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))
    else:
        raise HttpError(request, 501, "Not Implemented")

@authenticate(credentials=CREDENTIALS)
async def meters(request):
    payload = request.body
    dataKey = "meterData"
    result = "{}"
    
    if request.method == "POST":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            meter = json.loads(payload[dataKey])
            result = await meterController.AddMeter(payload["mqttSessionId"], meter)
        
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))        
    elif request.method == "GET":
        urlParts = request.url.split('/')
        print("url: " + request.url)
        print("url parts: " + str(urlParts))                
        id = urlParts[3]        
        operation = ""
        
        print("adr: " + str(len(urlParts)))
        
        if (len(urlParts) == 6):
            operation = urlParts[4]        

        print("operation: " + str(operation))
        
        # Return all meters
        if (id == ""):
            result = await meterController.GetAllMeters()
        elif (id == "count"):
            result = await meterController.GetMeterCount()
        else:
            if (operation == 'adr'):
                result = await meterController.GetAdr(id, True)
            else:                
                id = id.replace("%22", "'")
                result = await meterController.GetMeterById(id, True)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "PUT":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            id = urlParts[3]        
            meter = json.loads(payload[dataKey])
            result = await meterController.UpdateMeter(payload["mqttSessionId"], id, meter)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
  #      print("api: done update meter...: " + json.dumps(result))                        
    elif request.method == "DELETE":
        urlParts = request.url.split('/')
        id = ''
        
        if (len(urlParts) == 4):         
            id = urlParts[3]

        if (id == ''):
            result = await meterController.DeleteAllMeters()
        else:
            result = await meterController.DeleteMeter(payload["mqttSessionId"], id, payload["messageId"])
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))
    else:
        raise HttpError(request, 501, "Not Implemented")

@authenticate(credentials=CREDENTIALS)
async def asset_tasks(request):
    payload = request.body
    dataKey = "assetTaskData"
    result = "{}"
    
    if request.method == "POST":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            assetTask = json.loads(payload[dataKey])
            result = await assetTaskController.AddAssetTask(payload["mqttSessionId"], assetTask)
        
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))        
    elif request.method == "GET":
        urlParts = request.url.split('/')
        id = urlParts[3]        
        
        # Return all asset tasks
        if (id == ""):
            result = await assetTaskController.GetAllAssetTasks()
        elif (id == "count"):
            result = await assetTaskController.GetAssetTaskCount()            
        else:            
            id = id.replace("%22", "'")
            result = await assetTaskController.GetAssetTaskById(id, True)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "PUT":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):
            id = urlParts[3]
            assetTask = json.loads(payload[dataKey])
            result = await assetTaskController.UpdateAssetTask(payload["mqttSessionId"], id, assetTask)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "DELETE":
        urlParts = request.url.split('/')
        clientId = urlParts[3]        
        id = ''
        
        if (len(urlParts) == 4):         
            id = urlParts[3]
        
        if (id == ''):
            result = await assetTaskController.DeleteAllAssetTasks()
        else:
            result = await assetTaskController.DeleteAssetTask(payload["mqttSessionId"], id, payload["messageId"])
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))
    else:
        raise HttpError(request, 501, "Not Implemented")

@authenticate(credentials=CREDENTIALS)
async def meter_readings(request):
    payload = request.body
    dataKey = "meterReadingData"
    result = "{}"
    
    if request.method == "POST":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            meterReading = json.loads(payload[dataKey])                        
            result = await meterReadingController.AddMeterReading(payload["mqttSessionId"], meterReading)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))        
    elif request.method == "GET":
        urlParts = request.url.split('/')
        id = urlParts[3]        

        # Return all meterReadings
        if (id == ""):
            result = await meterReadingController.GetAllMeterReadings()
        elif (id == "count"):
            result = await meterReadingController.GetMeterReadingCount()
        else:
            id = id.replace("%22", "'")
            result = await meterReadingController.GetMeterReadingById(id, True)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "PUT":
        urlParts = request.url.split('/')
        
        if (dataKey in payload):        
            id = urlParts[3]
            meterReading = json.loads(payload[dataKey])                                
            result = await meterReadingController.UpdateMeterReading(payload["mqttSessionId"], id, meterReading)
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")
        await request.write(json.dumps(result))
    elif request.method == "DELETE":
        urlParts = request.url.split('/')
        clientId = urlParts[3]        
        id = ''
        
        if (len(urlParts) == 4):         
            id = urlParts[3]
               
        if (id == ''):
            result = await meterReadingController.DeleteAllMeterReadings()
        else:
            result = await meterReadingController.DeleteMeterReading(payload["mqttSessionId"], id, payload["messageId"])
            
        await request.write("HTTP/1.1 200 OK\r\n")
        await request.write("Content-Type: application/json\r\n\r\n")        
        await request.write(json.dumps(result))
    else:
        raise HttpError(request, 501, "Not Implemented")

def free(full=False):
#    gc.collect()        
    F = gc.mem_free()
    A = gc.mem_alloc()
    T = F + A
    P = '{0:.2f}%'.format(F/T*100)
    if not full: return P
    else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))

async def showMemUsage():
    while True:
        print(free(True))
        await asyncio.sleep(5)

async def monitorStatusQueues(success_q, error_q):
    while True:
        print("Error Queue length..." + str(len(error_q)))
        print("Success Queue length..." + str(len(success_q)))        

        for key, value in success_q.items():
            print(key, ' : ', value)

        for key, value in error_q.items():
            print(key, ' : ', value)

        print("Memory status..." + free(True))
#        print("Time..." + str(time.gmtime()))                
        await asyncio.sleep(3)

async def main():
    loop = asyncio.get_event_loop()
    loop.create_task(naw.run())
    loop.create_task(showMemUsage())

    loop.run_forever()

naw = Nanoweb(8001)
naw.assets_extensions += ('ico',)
naw.STATIC_DIR = EXAMPLE_ASSETS_DIR

naw.routes = {
    '/api/todoitems/': todo_items,
    '/api/assets/': assets,
    '/api/assettasks/': asset_tasks,
    '/api/meters/': meters,
    '/api/meterreadings/': meter_readings
    }

@naw.route("/ping")
async def ping(request):
    await request.write("HTTP/1.1 200 OK\r\n\r\n")
    await request.write("pong")

dir = sdDir

if (useMem == False):
    if (useRAMDisk == True):
        rootDir = '/rb'    
        bdev = RAMBlockDevExt(512, 500)
        os.VfsFat.mkfs(bdev)
        os.mount(bdev, rootDir)
        dir = rootDir + '/btree_storage'    
        os.mkdir(dir)
    else:
        rootDir = '/sd'
        dir = rootDir + '/btree_storage'            
        os.mount(pyb.SDCard(), rootDir)    

asyncio.run(Init(dir))
asyncio.run(main())    


    