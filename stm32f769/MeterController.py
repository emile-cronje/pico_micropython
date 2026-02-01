from Meter import Meter
import json

class MeterController:
    def __init__(self, mqttConnectionPool, dao, topics,
                 meterReadingController):
        self.meterDao = dao
        self.mqttConnectionPool = mqttConnectionPool
        self.topics = topics
        self.meterReadingController = meterReadingController
        
    async def AddMeter(self, mqttSessionId, post):
        post["version"] = 0
        post["adr"] = 0        
        messageId = post["messageId"]
        
        meter = await self.meterDao.AddMeter(post)

        if (meter == None):
            meter_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                            
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                                                    
                            "EntityType":"Meter",
                            "Operation":"Create"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_data))
                print("published not found meter add...")
                
            return                                
        else:        
            meter_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                            
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                                                    
                            "EntityType":"Meter",
                            "Operation":"Create",
                            "Entity" : json.dumps(meter)                                                        
                         }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_data))
            
        return meter            

    async def UpdateMeter(self, mqttSessionId, id, updatedMeter):
        savedMeter = await self.GetMeterById(id)
        messageId = updatedMeter["messageId"]

        if (savedMeter == None):
            return {"statusCode": 404, "message": "Meter not found"}
        else:        
            savedMeter["version"] = int(savedMeter["version"]) + 1
            savedMeter["code"] = updatedMeter["code"]
            savedMeter["description"] = updatedMeter["description"]
            savedMeter["isPaused"] = updatedMeter["isPaused"]
            savedMeter["messageId"] = messageId
            
            result = await self.meterDao.UpdateMeter(id, savedMeter)
            
            meter_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                            
                            "messageId": messageId,
                            "ClientId": savedMeter["clientId"],                                                                                                    
                            "EntityType":"Meter",
                            "Operation":"Update",                        
                            "Entity" : json.dumps(result)                                                        
                          }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_data))
            
            return result            

    async def GetMeterById(self, id, toJson = False):
        meter = await self.meterDao.GetMeterById(id)

        if (meter != None):
            jSonResult = meter

            if (toJson == True):
                return jSonResult
        else:
            return None

        return meter

    async def GetAdr(self, meterId, toJson = False):
        jSonResult = None
        adr = await self.meterReadingController.GetAdr(meterId)
        
        if (adr != None):
            jSonResult = adr

            if (toJson == True):
                return jSonResult

        return jSonResult

    async def GetAllMeters(self):
        result = await self.meterDao.GetAllMeters()
        return result

    async def DeleteAllMeters(self):
        result = await self.meterDao.DeleteAllMeters()
        return result

    async def DeleteMeter(self, mqttSessionId, id, messageId):
        savedMeter = await self.GetMeterById(id)
        
        if (savedMeter == None):
            meter_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                            
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"Meter",
                            "Operation":"Delete"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_data))

            return                
        else:
            await self.meterReadingController.DeleteMeterReadingsForMeter(mqttSessionId, id, messageId)
            result = await self.meterDao.DeleteMeter(id)
            
            meter_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                            
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"Meter",
                            "Operation":"Delete",                        
                            "Entity" : json.dumps(savedMeter)                                                                                                            
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(meter_data))
            
            return result

    async def GetMeterCount(self):
        result = await self.meterDao.GetMeterCount()
        return result