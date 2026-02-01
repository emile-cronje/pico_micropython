from Asset import Asset
import json

class AssetController:
    def __init__(self, mqttConnectionPool, dao, topics, assetTaskController):
        self.assetDao = dao
        self.mqttConnectionPool = mqttConnectionPool
        self.topics = topics
        self.assetTaskController = assetTaskController
        
    async def AddAsset(self, mqttSessionId, post):
        post["version"] = 0
        messageId = post["messageId"]
        
        asset = await self.assetDao.AddAsset(post)

        if (asset == None):
            asset_data = {
                            "MqttSessionId": mqttSessionId,
                            "messageId": messageId,
                            "ClientId": post["clientId"],
                            "EntityType":"Asset",
                            "Operation":"Create"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_data))
                print("published not found asset add...")
                
            return                
        else:        
            asset_data = {
                            "messageId": messageId,
                            "ClientId": post["clientId"],                                                                        
                            "EntityType":"Asset",
                            "Operation":"Create",                        
                            "Entity" : json.dumps(asset)                            
                         }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_data))
            
        return asset            

    async def UpdateAsset(self, mqttSessionId, id, updatedAsset):
        savedAsset = await self.GetAssetById(id)
        messageId = updatedAsset["messageId"]        
        
        if (savedAsset == None):
            return {"statusCode": 404, "message": "Asset not found"}
        else:        
            savedAsset["version"] = int(savedAsset["version"]) + 1
            savedAsset["code"] = updatedAsset["code"]
            savedAsset["description"] = updatedAsset["description"]
            savedAsset["isMsi"] = bool(updatedAsset["isMsi"])
            savedAsset["messageId"] = messageId            
            
            result = await self.assetDao.UpdateAsset(id, savedAsset)
            
            asset_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                            
                            "messageId": messageId,
                            "ClientId": savedAsset["clientId"],                                                                        
                            "EntityType":"Asset",
                            "Operation":"Update",                        
                            "Entity" : json.dumps(result)                            
                          }
            
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_data))
        
            return result            

    async def GetAssetById(self, id, toJson = False):
        asset = await self.assetDao.GetAssetById(id)

        if (asset != None):
            jSonResult = asset

            if (toJson == True):
                return jSonResult
        else:
            return None

        return asset

    async def GetAllAssets(self):
        result = await self.assetDao.GetAllAssets()
        return result

    async def DeleteAllAssets(self):
        result = await self.assetDao.DeleteAllAssets()
        return result

    async def DeleteAsset(self, mqttSessionId, id, messageId):
        savedAsset = await self.GetAssetById(id)
        
        if (savedAsset == None):
            asset_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                                            
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"Asset",
                            "Operation":"Delete"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_data))
                print("published not found asset delete...")
            return                
        else:
            await self.assetTaskController.DeleteAssetTasksForAsset(mqttSessionId, messageId, id)                    
            result = await self.assetDao.DeleteAsset(id)
            
            asset_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                                            
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"Asset",
                            "Operation":"Delete",                        
                            "Entity" : json.dumps(savedAsset)                                                                                                            
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(asset_data))
                print("published asset delete...")
            
            return result

    async def GetAssetCount(self):
        result = await self.assetDao.GetAssetCount()
        return result
