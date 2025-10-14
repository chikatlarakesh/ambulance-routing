from pydantic import BaseModel
from datetime import datetime

class RerouteCheck(BaseModel):
    ambulance_id: str
    current_time: datetime  # ISO format e.g., "2025-10-14T09:10:00Z"