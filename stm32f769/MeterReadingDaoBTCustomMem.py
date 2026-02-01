import json
from MeterReading import MeterReading
import time
import utime
from AdrHelper import AdrHelper

class MeterReadingDaoBT:
    def __init__(self, btree, meterDao, adr_window_size=30):
        self.db = btree
        self.meterDao = meterDao
        self.adrHelper = AdrHelper()
        self.adr_window_size = adr_window_size  # Number of recent readings to use for ADR calculation        
       
    async def AddMeterReading(self, meterReading):
        db = self.db
        meterReading["id"] = str(time.time_ns())                
        meter = await self.meterDao.GetMeterById(str(meterReading["meterId"]))
        
        if (meter == None):
            newMeterReading = None
        else:            
            db.insert((meterReading["id"], meterReading))
            newMeterReading = await self.GetMeterReadingById(meterReading["id"])
        
        return newMeterReading
       
    async def UpdateMeterReading(self, id, meterReading):
        db = self.db
        db.update_value(id, meterReading)        
        
        updatedMeterReading = await self.GetMeterReadingById(id)
        
        return updatedMeterReading

    async def GetMeterReadingById(self, id):
        db = self.db
        savedMeterReading = db.find(id)
        return savedMeterReading

    async def GetAllMeterReadings(self):
        db = self.db
        result = []
        
        for key in db:
            meter = db.get_value(key)
            result.append(json.loads(meter))
            
        return result

    async def GetMeterReadingCount(self):
        db = self.db
        return db.count_all()
        
    async def DeleteMeterReading(self, id):
        db = self.db
        result = "MeterReading not found..."

        if (db.find(id) != None):
            db.delete(id)                
            result = "MeterReading deleted..."            
            
        return result                    

    async def DeleteAllMeterReadings(self):
        db = self.db
        db.delete_all()
        
        result = "All MeterReadings deleted..."            
        return result
    
    async def GetReadingsForMeter(self, meterId):
        db = self.db
        filter_func = lambda reading: str(reading["meterId"]) == str(meterId)
        meter_readings = db.traverse_func(filter_func)
        
        return meter_readings
    
    async def GetAdr(self, meterId):
        """Calculate ADR using only the most recent readings (window approach)"""
        meterReadings = await self.GetReadingsForMeter(meterId)
        
        if not meterReadings or len(meterReadings) == 0:
            return 0
        
        # Sort all readings by date
        meterReadings = self.adrHelper.sort_json_objects_by_date(meterReadings)
        
        # Use only the most recent N readings (window)
        if len(meterReadings) > self.adr_window_size:
            meterReadings = meterReadings[-self.adr_window_size:]
        
        # Calculate ADR on the windowed data
        adr = self.adrHelper.calculate_average_daily_rate(meterReadings)
        return adr
    
    async def GetReadingCountForMeter(self, meterId):
        db = self.db
        filter_func = lambda reading: str(reading["meterId"]) == str(meterId)
        readings = db.traverse_func(filter_func)
        
        return len(readings)

    async def GetReadingIdsForMeter(self, meterId):
        readingCount = await self.GetReadingCountForMeter(meterId)
        
        if (readingCount <= 0):
            return None
        
        readings = await self.GetReadingsForMeter(meterId)        
        readingIds = []

        for reading in readings:
            readingIds.append(reading["id"])

        return readingIds    