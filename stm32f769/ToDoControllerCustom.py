from ToDoItem import ToDoItem
import ujson
import time

class ToDoController:
    def __init__(self, mqtt_client, dao):
        self.todoDao = dao
        self.mqtt_client = mqtt_client
        self.topic = 'entities'
        
    async def AddItem(self, item):
        todoItem = ToDoItem()
        todoItem.id = str(time.time_ns())
        todoItem.version = 0
        todoItem.name = str(item["name"])
        todoItem.description = str(item["description"])
        todoItem.isComplete = bool(item["isComplete"])
        item = await self.todoDao.AddItem(todoItem)

        if (self.mqtt_client != None) and (item != None):
            item_data = {
                            "EntityType":"ToDoItem",
                            "Operation":"Create",                                                
                            "Entity" : ujson.dumps(item)
                        }
            await self.mqtt_client.publish(self.topic, ujson.dumps(item_data), qos = 1)
            
        return item            

    async def UpdateItem(self, id, updatedItem):
        savedItem = await self.GetItemById(id)
        
        if (savedItem != None):
            savedItem.version = savedItem.version + 1                        
            savedItem.name = str(updatedItem["name"])
            savedItem.description = str(updatedItem["description"])
            savedItem.isComplete = bool(updatedItem["isComplete"])
            result = await self.todoDao.UpdateItem(id, savedItem)
            
            if (self.mqtt_client != None):            
                item_data = {
                                "EntityType":"ToDoItem",
                                "Operation":"Update",                        
                                "Entity" : ujson.dumps(result.__dict__)
                             }
                
                await self.mqtt_client.publish(self.topic, ujson.dumps(item_data), qos = 1)
                result = "Item updated..."
        else:
            result = {"statusCode": 404, "message": "ToDo item not found"}
            
        return result            

    async def GetItemById(self, id, toJson = False):
        item = await self.todoDao.GetItemById(id)
        
        if (item != None):        
            jSonResult = ujson.loads(ujson.dumps(item.__dict__))

            if (toJson == True):
                return jSonResult

        return item

    async def GetAllItems(self):
        result = await self.todoDao.GetAllItems()
        return result

    async def DeleteAllItems(self):
        result = await self.todoDao.DeleteAllItems()
        return result

    async def DeleteItem(self, id):
        result = await self.todoDao.DeleteItem(id)
        return result

    async def GetItemCount(self):
        result = await self.todoDao.GetItemCount()
        return result
