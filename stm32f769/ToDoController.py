from ToDoItem import ToDoItem
import json

class ToDoController:
    def __init__(self, mqttConnectionPool, dao, topics):
        self.todoDao = dao
        self.mqttConnectionPool = mqttConnectionPool
        self.topics = topics
        
    async def AddItem(self, mqttSessionId, item):
        item["version"] = 0        
        messageId = item["messageId"]
        
        savedItem = await self.todoDao.AddItem(item)

        if (savedItem == None):
            item_data = {
                            "MqttSessionId": mqttSessionId,                                                                                            
                            "messageId": messageId,
                            "ClientId": item["clientId"],
                            "EntityType":"ToDoItem",
                            "Operation":"Create"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(item_data))
                print("published not found todo add...")
                
            return                
        else:
            item_data = {
                            "MqttSessionId": mqttSessionId,                                                                                            
                            "messageId": messageId,
                            "ClientId": item["clientId"],                                                                        
                            "EntityType":"ToDoItem",
                            "Operation":"Create",
                            "Entity" : json.dumps(savedItem)                                                                                    
                        }
           
            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(item_data))
            
        return savedItem

    async def UpdateItem(self, mqttSessionId, id, updatedItem):
        savedItem = await self.GetItemById(id)
        messageId = updatedItem["messageId"]
        
        if (savedItem == None):
            return {"statusCode": 404, "message": "ToDo item not found"}
        else:
            version = savedItem["version"]
            version += 1
            savedItem["version"] = version
            savedItem["name"] = updatedItem["name"]
            savedItem["description"] = updatedItem["description"]
            savedItem["isComplete"] = bool(updatedItem["isComplete"])
            savedItem["messageId"] = messageId
                
            result = await self.todoDao.UpdateItem(id, savedItem)
            
            item_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                                
                            "messageId": messageId,
                            "ClientId": savedItem["clientId"],                                                                        
                            "EntityType":"ToDoItem",
                            "Operation":"Update",                        
                            "Entity" : json.dumps(result),
                            "entityId": id                            
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(item_data))

            return result            

    async def GetItemById(self, id, toJson = False):
        item = await self.todoDao.GetItemById(id)
        return item        
        
    async def GetAllItems(self):
        result = await self.todoDao.GetAllItems()            
        return result

    async def DeleteAllItems(self):
        result = await self.todoDao.DeleteAllItems()
        return result

    async def DeleteItem(self, mqttSessionId, id, messageId):
        savedItem = await self.GetItemById(id)
        
        if (savedItem == None):
            item_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                                                
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"ToDoItem",
                            "Operation":"Delete"
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(item_data))
                print("published not found todo delete..." + str(id))
            return                
        else:            
            result = await self.todoDao.DeleteItem(id)
            
            item_data = {
                            "MqttSessionId": mqttSessionId,                                                                                                                                                                    
                            "messageId": messageId,
                            "ClientId": id,                                                                            
                            "EntityType":"ToDoItem",
                            "Operation":"Delete",
                            "Entity" : json.dumps(savedItem)                                                                                                            
                         }

            for topic in self.topics:
                await self.mqttConnectionPool.Publish(topic, json.dumps(item_data))
                print("published todo delete..." + str(id))            
        
        return result

    async def GetItemCount(self):
        result = await self.todoDao.GetItemCount()
        return result
