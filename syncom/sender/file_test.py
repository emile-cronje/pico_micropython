import utime,time
from ubinascii import hexlify
import ubinascii
import uhashlib
import ujson
import os
import uasyncio as asyncio
from pbmqtt import MQTTlink
import hw_pico as hardware
import net_local
from queue import Queue
import gc

_send_q = Queue()
_file_wait_q = Queue()
_file_in_progress_q = Queue()
_qos = 1
_data_block_size = 20
_out_hash_md5 = uhashlib.sha256()
_file_block_sequence_nr = 0
_topic_files = 'pico1_files'
_event_file_ready_for_backup = asyncio.Event()
_event_file_backup_completed = asyncio.Event()
_event_send_q_ready = asyncio.Event()

_do_file_backup = True
_msg_id = 1
_do_selected_files = True
_do_test_messages = False
_do_all_files = False

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

async def sender(mqtt_link, msg_q):
    print("sender start...")

    while True:
        if (msg_q.qsize() > 0):
            msg = await msg_q.get()
            print("publishing...:" + msg)            
            
            await mqtt_link.publish(_topic_files, msg, False, _qos)
            await asyncio.sleep_ms(100)
            
        await asyncio.sleep_ms(500)            
      
def batch_strings(strings, batch_size):
    while strings:
        batch = strings[:batch_size]
        strings = strings[batch_size:]
        yield batch

async def get_all_files(msg_q):
    filenames = []

    print("Starting backup_all_files...")
    await send_start(msg_q)    
    
    _event_file_ready_for_backup.clear()
    _event_file_backup_completed.clear()

    if (_do_selected_files == True):
        filenames = []
        filenames.append('test.txt')        
        #filenames.append('syncom.py')        
        #filenames.append('net_local.py')
        #filenames.append('net_local_1.py')
        #filenames.append('net_local_2.py')
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
        await _file_wait_q.put(filename)

    _event_file_backup_completed.set()                

async def processFile(fileName, msg_q):
    global _out_hash_md5
    global _data_block_size
    global _file_block_sequence_nr
    
    _event_file_ready_for_backup.clear()    
    print("Starting backup single file...")
            
    if file_exist(fileName):
        fo = open(fileName, "rb")
        file_properties = os.stat(fileName)
        file_size = file_properties[6]
        
        await send_header(fileName, file_size, msg_q)
        
        print("file opened...%s" % fileName)
        run_flag = True
        _out_hash_md5 = uhashlib.sha256()
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
    global _out_hash_md5
    
    print("Preparing block...")        
    _out_hash_md5.update(file_content)    
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
    global _out_hash_md5
    
    print("Preparing end...")        
    base64_hash_data = ubinascii.b2a_base64(_out_hash_md5.digest())[:-1]
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

async def main(mqtt_link, send_q):
    await asyncio.sleep(5)
    
    if (_do_test_messages == True):
        asyncio.create_task(publish_test(mqtt_link))

    if (_do_file_backup == True):
        await get_all_files(send_q)

    asyncio.create_task(sender(mqtt_link, send_q))
    
    print("main running...")
    
    while True:
        await asyncio.sleep(5)

def free(full=False):
#  gc.collect()
  F = gc.mem_free()
  A = gc.mem_alloc()
  T = F+A
  P = '{0:.2f}%'.format(F/T*100)
  if not full: return P
  else : return ('Total:{0} Free:{1} ({2})'.format(T,F,P))

async def monitorQueueLength(msg_q):
    while True:
        if (msg_q.qsize() > 10):        
            _event_send_q_ready.clear()            
        else:
            _event_send_q_ready.set()            

        print("Memory status..." + free(True))
        await asyncio.sleep(5)

async def fileQueueProducer():
    while True:
        await _event_file_backup_completed.wait()

        _event_file_backup_completed.clear()        
        fileName = await _file_wait_q.get()
        await _file_in_progress_q.put(fileName)
        _event_file_ready_for_backup.set()
        await asyncio.sleep(1)

async def fileQueueConsumer(msg_q):
    while True:
        await _event_file_ready_for_backup.wait()
        await _event_send_q_ready.wait()

        _event_file_backup_completed.clear()
        _event_file_ready_for_backup.clear()
        fileName = await _file_in_progress_q.get()

        await processFile(fileName, msg_q)
        gc.collect()

        _event_file_backup_completed.set()        
        await asyncio.sleep(.5)

try:
    MQTTlink.will('result', 'simple client died')
    mqtt_link = MQTTlink(hardware.d, net_local.d, wifi_handler=(cbnet,()), verbose=True)

    asyncio.create_task(monitorQueueLength(_send_q))
    asyncio.create_task(fileQueueProducer())            
    asyncio.create_task(fileQueueConsumer(_send_q))
    asyncio.run(main(mqtt_link, _send_q))        
finally:
    asyncio.new_event_loop()
