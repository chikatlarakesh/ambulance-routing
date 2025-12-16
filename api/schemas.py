from pydantic import BaseModel
from datetime import datetime

class RerouteCheck(BaseModel):
    ambulance_id: str
