from AssetTask import AssetTask
import json

class AssetTaskController:
    def __init__(self, mqttConnectionPool, dao, topics):
        self.assetTaskDao = dao
        self.mqttConnectionPool = mqttConnectionPool
        self.topics = topics
        
    async def AddAssetTask(self, mqttSessionId, post):
        post["version"] = 0
        messageId = post["messageId"]
        
        assetTask = await self.assetTaskDao.AddAssetTask(post)

        if (assetTask == None):
            asset_task_data = {
                            "MqttSessionId": mqttSessionId,                
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                        
                            "EntityType":"AssetTask",
                            "Operation":"Create"
                         }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_task_data))
                
            return                
        else:            
            asset_task_data = {
                            "MqttSessionId": mqttSessionId,                
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                        
                            "EntityType":"AssetTask",
                            "Operation":"Create",                        
                            "Entity" : json.dumps(assetTask)                            
                         }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_task_data))
          
            return assetTask            

    async def UpdateAssetTask(self, mqttSessionId, id, updatedAssetTask):
        savedAssetTask = await self.GetAssetTaskById(id)
        messageId = updatedAssetTask["messageId"]                
        
        if (savedAssetTask == None):
            return {"statusCode": 404, "message": "Asset task not found"}
        else:        
            savedAssetTask["version"] = int(savedAssetTask["version"]) + 1
            savedAssetTask["code"] = updatedAssetTask["code"]
            savedAssetTask["description"] = updatedAssetTask["description"]
            savedAssetTask["isRfs"] = bool(updatedAssetTask["isRfs"])
            savedAssetTask["messageId"] = messageId                        
            
            result = await self.assetTaskDao.UpdateAssetTask(id, savedAssetTask)
            
            asset_task_data = {
                            "MqttSessionId": mqttSessionId,                
                            "messageId": messageId,
                            "ClientId": savedAssetTask["clientId"],                                                                        
                            "EntityType":"AssetTask",
                            "Operation":"Update",                        
                            "Entity" : json.dumps(result)                            
                          }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_task_data))
                
            return result            

    async def GetAssetTaskById(self, id, toJson = False):
        assetTask = await self.assetTaskDao.GetAssetTaskById(id)

        if (assetTask != None):
            jSonResult = assetTask

            if (toJson == True):
                return jSonResult
        else:
            return None

        return assetTask

    async def GetAllAssetTasks(self):
        result = await self.assetTaskDao.GetAllAssetTasks()
        return result

    async def DeleteAllAssetTasks(self):
        print("Deleting all Asset Tasks...")
        result = await self.assetTaskDao.DeleteAllAssetTasks()
        return result

    async def DeleteAssetTask(self, mqttSessionId, id, messageId):
        savedAssetTask = await self.GetAssetTaskById(id)
        
        if (savedAssetTask == None):
            asset_task_data = {
                            "MqttSessionId": mqttSessionId,                
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"AssetTask",
                            "Operation":"Delete"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_task_data))
                print("published not found asset task delete...")
            return                
        else:            
            result = await self.assetTaskDao.DeleteAssetTask(id)
            
            task_data = {
                            "MqttSessionId": mqttSessionId,                
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"AssetTask",
                            "Operation":"Delete",                        
                            "Entity" : json.dumps(savedAssetTask)                                                                                                            
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(task_data))
                print("published asset task delete...")            
            
            return result

    async def DeleteAssetTasksForAsset(self, mqttSessionId, messageId, assetId):
        taskIds = await self.assetTaskDao.GetTaskIdsForAsset(assetId)

        if (taskIds != None):
            for taskId in taskIds:
                await self.DeleteAssetTask(mqttSessionId, taskId, messageId)
            
    async def GetAssetTaskCount(self):
        result = await self.assetTaskDao.GetAssetTaskCount()
        return result
