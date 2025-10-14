from pydantic import BaseModel

class RerouteCheck(BaseModel):
    ambulance_id: str
    current_time: str  # ISO format e.g., "2025-10-14T09:10:00Z"