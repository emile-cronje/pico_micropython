from MeterReading import MeterReading
import json

class MeterReadingController:
    def __init__(self, mqttConnectionPool, dao, topics):
        self.meterReadingDao = dao
        self.mqttConnectionPool = mqttConnectionPool
        self.topics = topics
        
    async def AddMeterReading(self, mqttSessionId, post):
        post["version"] = 0
        messageId = post["messageId"]
        
        meterReading = await self.meterReadingDao.AddMeterReading(post)

        if (meterReading == None):
            reading_data = {
                            "MqttSessionId": mqttSessionId,                                
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                        
                            "EntityType":"MeterReading",
                            "Operation":"Create"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(reading_data))
                
            return                
        else:        
            meterReading_data = {
                            "MqttSessionId": mqttSessionId,                                
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                        
                            "EntityType":"MeterReading",
                            "Operation":"Create",                        
                            "Entity" : json.dumps(meterReading)                            
                         }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meterReading_data))
            
        return meterReading            

    async def UpdateMeterReading(self, mqttSessionId, id, updatedMeterReading):
        savedMeterReading = await self.GetMeterReadingById(id)
        messageId = updatedMeterReading["messageId"]                
        
        if (savedMeterReading == None):
            return {"statusCode": 404, "message": "Meter reading not found"}
        else:        
            savedMeterReading["version"] = int(savedMeterReading["version"]) + 1            
            savedMeterReading["reading"] = updatedMeterReading["reading"]
            #savedMeterReading["readingOn"] = updatedMeterReading["readingOn"]
            savedMeterReading["messageId"] = messageId            
            
            result = await self.meterReadingDao.UpdateMeterReading(id, savedMeterReading)
            
            meter_reading_data = {
                            "MqttSessionId": mqttSessionId,                                
                            "messageId": messageId,
                            "ClientId": savedMeterReading["clientId"],                                                                        
                            "EntityType":"MeterReading",
                            "Operation":"Update",                        
                            "Entity" : json.dumps(result)                                                        
                          }

            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_reading_data))
                
            result = "Meter reading updated..."            
            
            return result            

    async def GetMeterReadingById(self, id, toJson = False):
        meterReading = await self.meterReadingDao.GetMeterReadingById(id)

        if (meterReading != None):
            jSonResult = meterReading

            if (toJson == True):
                return jSonResult
        else:
            return None
            
        return meterReading

    async def GetAllMeterReadings(self):
        result = await self.meterReadingDao.GetAllMeterReadings()
        return result

    async def GetReadingsForMeter(self, meterId):
        result = await self.meterReadingDao.GetReadingsForMeter(meterId)
        return result

    async def DeleteAllMeterReadings(self):
        result = await self.meterReadingDao.DeleteAllMeterReadings()
        return result

    async def DeleteMeterReading(self, mqttSessionId, id, messageId):
        savedMeterReading = await self.GetMeterReadingById(id)
        
        if (savedMeterReading == None):
            meter_reading_data = {
                            "MqttSessionId": mqttSessionId,                                
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"MeterReading",
                            "Operation":"Delete"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_reading_data))

            return                
        else:
            result = await self.meterReadingDao.DeleteMeterReading(id)
            
            meter_reading_data = {
                            "MqttSessionId": mqttSessionId,                                
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"MeterReading",
                            "Operation":"Delete",                        
                            "Entity" : json.dumps(savedMeterReading)                                                                                                            
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_reading_data))
            
            return result

    async def DeleteMeterReadingsForMeter(self, mqttSessionId, messageId, meterId):
        readingIds = await self.meterReadingDao.GetReadingIdsForMeter(meterId)

        if (readingIds != None):
            for readingId in readingIds:
                await self.DeleteMeterReading(mqttSessionId, readingId, messageId)

    async def GetMeterReadingCount(self):
        result = await self.meterReadingDao.GetMeterReadingCount()
        return result

    async def GetAdr(self, meterId):
        adr = await self.meterReadingDao.GetAdr(meterId)
        print("Controller - GetAdr: " + str(adr))
        return adr
        
