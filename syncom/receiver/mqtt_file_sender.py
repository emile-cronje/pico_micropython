import utime,time
from ubinascii import hexlify
import ubinascii
import uhashlib
import ujson
import os
import uasyncio as asyncio
from queue import Queue
import gc
from mqtt_as_latest import MQTTClient, config
#from mqtt_as import MQTTClient, config

_send_q = Queue()
_file_wait_q = Queue()
_file_in_progress_q = Queue()
_qos = 1
_data_block_size = 250
_out_hash_sha256 = uhashlib.sha256()
_file_block_sequence_nr = 0
_topic_files = 'pico2w_file_sync'
_event_file_ready_to_send = asyncio.Event()

_do_file_backup = True
_msg_id = 1
_do_selected_files = True
_do_test_messages = False
_do_all_files = False

async def getAllFiles(msg_q, file_wait_q):
    filenames = []

    print("Starting backup_all_files...")
    await send_start(msg_q)    
    
    _event_file_ready_to_send.clear()

    if (_do_selected_files == True):
        filenames = []
        
        #filenames.append('test.txt')        
        filenames.append('syncom.py')        
        filenames.append('test.txt')
#        filenames.append('net_local_1.py')
 #       filenames.append('net_local_2.py')
   #     filenames.append('pbmqtt.py')
  #      filenames.append('queue.py')
 #       filenames.append('main.py')
#        filenames.append('syncom_orig.py')
  #      filenames.append('status_values.py')
   #     filenames.append('pico_simple.py')
    #    filenames.append('syncom_test_host.py')
     #   filenames.append('syncom_test_host_one_task.py')                                        
    elif (_do_all_files == True):
        for filename in os.listdir():
            filenames.append(filename)

    for filename in filenames:
        await file_wait_q.put(filename)

def get_msg_id():
    global _msg_id

    result = _msg_id
    _msg_id += 1
    
    return result

def build_msg(msg_in):
    out_hash_md5 = uhashlib.sha256()
    
    # create a hash of the message    
    out_hash_md5.update(msg_in)
    
    # encode the msg in base64
    base64_msg = ubinascii.b2a_base64(msg_in)
    
    # encode the msg hash in base64    
    base64_hash_msg = ubinascii.b2a_base64(out_hash_md5.digest())[:-1]
    
    msg =   {
                "Category": 'Test',                                
                "Message": msg_in,        
                "Base64Message": base64_msg,
                "Base64MessageHash": base64_hash_msg
            }
    
    return ujson.dumps(msg)

async def publish_test(mqtt_link):
    count = 1
    
    while True:
        msgToSend = build_msg(str(count))
        
        await mqtt_link.publish('pico1_test', msgToSend, False, _qos)
        
        print("published...: " + msgToSend)                
        count += 1
        await asyncio.sleep_ms(500)

async def fileSender(mqtt_link, msg_q):
    print("fileSender start...")

    while True:
        if (msg_q.qsize() > 0):
            msg = await msg_q.get()
            print("publishing to...: \r\n" + _topic_files)                        
           
            await mqtt_link.publish(_topic_files, msg, False, _qos)
            print("published...: \r\n" + msg)                        
            await asyncio.sleep_ms(100)
            
        await asyncio.sleep_ms(500)            
      
def batch_strings(strings, batch_size):
    while strings:
        batch = strings[:batch_size]
        strings = strings[batch_size:]
        yield batch

async def processFile(fileName, msg_q):
    global _out_hash_sha256
    global _data_block_size
    global _file_block_sequence_nr
    
    _event_file_ready_to_send.clear()    
    print("Starting backup single file...")
            
    if file_exist(fileName):
        fo = open(fileName, "rb")
        file_properties = os.stat(fileName)
        file_size = file_properties[6]
        
        await send_header(fileName, file_size, msg_q)
        
        print("file opened...%s" % fileName)
        run_flag = True
        _out_hash_sha256 = uhashlib.sha256()
        _file_block_sequence_nr = 1
        nr_bytes_read = 0
        
        while run_flag:
            file_block = fo.read(_data_block_size)
            nr_bytes_read += len(file_block)
            
            if file_block:
                await send_file_block(fileName, file_block, file_size, nr_bytes_read, _file_block_sequence_nr, msg_q)
                _file_block_sequence_nr += 1                    
            else:
                await send_end(fileName, msg_q)
                run_flag = False
                fo.close()
    else:
        print("file %s not found" % fileName)

def file_exist(filename):
    try:
        f = open(filename, "r")
        exists = True
        f.close()
    except OSError:
        exists = False
    return exists

async def send_start(msg_q):
    print("Sending start...")
    msgId = get_msg_id()
    
    file_operation = {
                    "Id": msgId,
                    "Step": 'Start',                                        
                    "Category": 'Files',                        
                    "Operation": 'Backup',
                    "RspReceivedOK": False                    
                }
    
    payload = ujson.dumps(file_operation)
    await msg_q.put(payload)
    print("Start added to queue...")    

async def send_header(fileName, fileSize, msg_q):
    print("Preparing header...")
    msgId = get_msg_id()
    
    file_operation = {
                    "Id": msgId,
                    "Step": 'Header',                                        
                    "Category": 'Files',                        
                    "Operation": 'Backup',
                    "FileName":fileName,
                    "FileSize":fileSize,
                    "RspReceivedOK": False                    
                }
    
    payload = ujson.dumps(file_operation)
    await msg_q.put(payload)
    print("Header added to queue...")    

async def send_file_block(file_name, file_content, file_size, nr_bytes_read, _file_block_sequence_nr, msg_q):
    global _out_hash_sha256
    
    print("Preparing block...")        
    _out_hash_sha256.update(file_content)    
    base64_data = ubinascii.b2a_base64(file_content)
    percentage = ((nr_bytes_read) / file_size) * 100
    msgId = get_msg_id()
    
    file_operation = {
                    "Id": msgId,
                    "Step": 'Content',                            
                    "Category": 'Files',
                    "Operation": 'Backup',                    
                    "FileName":file_name,        
                    "FileData":base64_data,
                    "FileBlockSequenceNumber": _file_block_sequence_nr,
                    "ProgressPercentage": str(percentage),
                    "RspReceivedOK": False                    
                 }
    
    payload = ujson.dumps(file_operation)
    await msg_q.put(payload)

async def send_end(filename, msg_q):
    global _out_hash_sha256
    
    print("Preparing end...")        
    base64_hash_data = ubinascii.b2a_base64(_out_hash_sha256.digest())[:-1]
    msgId = get_msg_id()
    
    file_operation = {
                    "Id": msgId,
                    "Step": 'End',                                    
                    "Category": 'Files',
                    "Operation": 'Backup',                    
                    "FileName":filename,
                    "HashData":base64_hash_data,
                    "RspReceivedOK": False
                }
    
    payload = ujson.dumps(file_operation)
    await msg_q.put(payload)

def cbnet(state, _):  # Show WiFi state. Discard mqtt_link arg.
    print('cbnet: network is ', 'up' if state else 'down')

def free(full=False):
#  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))

async def monitorQueueLength(send_q):
    while True:
        print("Memory status..." + free(True))
        print("Q size..." + str(send_q.qsize()))        
        await asyncio.sleep(5)

async def fileQueueProducer(file_wait_q, file_in_progress_q):
    while True:
        fileName = await file_wait_q.get()
        
        await file_in_progress_q.put(fileName)
        
        _event_file_ready_to_send.set()
        await asyncio.sleep(1)

async def fileQueueConsumer(msg_q, file_in_progress_q):
    while True:
        await _event_file_ready_to_send.wait()

        _event_file_ready_to_send.clear()
        fileName = await file_in_progress_q.get()

        await processFile(fileName, msg_q)
        await asyncio.sleep(.5)

async def main(mqtt_link, send_q, file_wait_q):
    await mqtt_link.connect()
    
    if (_do_test_messages == True):
        asyncio.create_task(publish_test(mqtt_link))

    if (_do_file_backup == True):
        await getAllFiles(send_q, file_wait_q)

    asyncio.create_task(fileSender(mqtt_link, send_q))
    
    print("main running...")
    
    while True:
        await asyncio.sleep(5)

def callback(topic, msg_in, retained):
    global _success_q, _error_q
    #print((topic, msg_in, retained))
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
            print("Test: " + message)
    
async def conn_han(client):
    await client.subscribe('pico1_files', 1)
    print("subscribed to pico1_files...")
    await client.subscribe('pico1_test', 1)
    print("subscribed to pico1_test...")
    await client.subscribe('file_test', 1)
    print("subscribed to file_test...")

SERVER = '192.168.10.174' #bbb

#config['subs_cb'] = callback
#config['connect_coro'] = conn_han
config['server'] = SERVER
config['ssid'] = 'Cudy24G'
config['wifi_pw'] = 'ZAnne19991214'

client = MQTTClient(config)

try:
    asyncio.create_task(fileQueueProducer(_file_wait_q, _file_in_progress_q))            
    asyncio.create_task(fileQueueConsumer(_send_q, _file_in_progress_q))
    asyncio.create_task(monitorQueueLength(_send_q))    
    asyncio.run(main(client, _send_q, _file_wait_q))        
finally:
    asyncio.new_event_loop()
