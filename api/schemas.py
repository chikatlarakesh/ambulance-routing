"""
Pydantic request / response schemas for the ambulance routing API.
"""

import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from core.config import (
    ABSOLUTE_TIME_MIN,
    AMBULANCE_ID_MAX_LEN,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MAX_EDGE_UPDATES_PER_SNAPSHOT,
    MULTIPLIER_MAX,
    MULTIPLIER_MIN,
)
from core.graph import EdgeUpdate

# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class LatLon(BaseModel):
    lat: float = Field(..., ge=LAT_MIN, le=LAT_MAX, description="Latitude in decimal degrees")
    lon: float = Field(..., ge=LON_MIN, le=LON_MAX, description="Longitude in decimal degrees")


class TimeDuration(BaseModel):
    minutes: int = Field(..., description="Whole minutes component")
    seconds: int = Field(..., description="Remaining seconds component (0-59)")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class RouteRequest(BaseModel):
    ambulance_id: Optional[str] = Field(
        None,
        max_length=AMBULANCE_ID_MAX_LEN,
        description="Unique identifier for the ambulance. Required to track the route.",
        examples=["AMB-001"],
    )
    current_location: LatLon = Field(..., description="Current GPS location of the ambulance")
    destination: LatLon = Field(..., description="Destination GPS location")
    departure_time: Optional[datetime.datetime] = Field(
        None,
        description="UTC departure time (ISO-8601). Defaults to now if omitted.",
        examples=["2026-06-12T08:00:00Z"],
    )
    constraints: Optional[Dict[str, Any]] = Field(
        None,
        description="Reserved for future constraint extensions (ignored currently).",
    )

    @field_validator("ambulance_id")
    @classmethod
    def ambulance_id_printable(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.isprintable():
            raise ValueError("ambulance_id must contain only printable characters")
        return v


class RouteResponse(BaseModel):
    ambulance_id: Optional[str] = Field(None, description="Echo of the requested ambulance_id")
    algorithm: str = Field(..., description="Algorithm used: 'dijkstra' or 'astar'")
    total_time_minutes: TimeDuration = Field(..., description="Estimated total travel time")
    estimated_arrival: str = Field(..., description="UTC arrival datetime (ISO-8601)")
    route_steps: List[str] = Field(..., description="Human-readable per-segment descriptions")
    path: List[int] = Field(..., description="Ordered list of node IDs from origin to destination")


# ---------------------------------------------------------------------------
# Traffic
# ---------------------------------------------------------------------------


class ValidatedEdgeUpdate(EdgeUpdate):
    @field_validator("multiplier")
    @classmethod
    def multiplier_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (MULTIPLIER_MIN <= v <= MULTIPLIER_MAX):
            raise ValueError(f"multiplier must be between {MULTIPLIER_MIN} and {MULTIPLIER_MAX}")
        return v

    @field_validator("absolute_time")
    @classmethod
    def absolute_time_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < ABSOLUTE_TIME_MIN:
            raise ValueError(f"absolute_time must be >= {ABSOLUTE_TIME_MIN} seconds")
        return v


class TrafficSnapshot(BaseModel):
    timestamp: datetime.datetime = Field(
        ...,
        description="UTC timestamp when this snapshot was captured",
        examples=["2026-06-12T08:05:00Z"],
    )
    edge_updates: List[ValidatedEdgeUpdate] = Field(
        ...,
        description="List of edge updates to apply",
        max_length=MAX_EDGE_UPDATES_PER_SNAPSHOT,
    )


# ---------------------------------------------------------------------------
# Position / reroute
# ---------------------------------------------------------------------------


class RerouteCheck(BaseModel):
    ambulance_id: str = Field(
        ...,
        max_length=AMBULANCE_ID_MAX_LEN,
        description="ID of the ambulance to evaluate for rerouting",
        examples=["AMB-001"],
    )

    @field_validator("ambulance_id")
    @classmethod
    def ambulance_id_printable(cls, v: str) -> str:
        if not v.isprintable():
            raise ValueError("ambulance_id must contain only printable characters")
        return v


class PositionUpdate(BaseModel):
    ambulance_id: str = Field(
        ...,
        max_length=AMBULANCE_ID_MAX_LEN,
        description="ID of the ambulance reporting its position",
        examples=["AMB-001"],
    )
    lat: float = Field(..., ge=LAT_MIN, le=LAT_MAX, description="Current latitude")
    lon: float = Field(..., ge=LON_MIN, le=LON_MAX, description="Current longitude")
    timestamp: Optional[datetime.datetime] = Field(
        None,
        description="UTC timestamp of this position report. Defaults to now.",
        examples=["2026-06-12T08:01:30Z"],
    )

    @field_validator("ambulance_id")
    @classmethod
    def ambulance_id_printable(cls, v: str) -> str:
        if not v.isprintable():
            raise ValueError("ambulance_id must contain only printable characters")
        return v


# ---------------------------------------------------------------------------
# Route status enum (shared between api/main.py and response payloads)
# ---------------------------------------------------------------------------


class RouteStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    REROUTED = "REROUTED"
    ARRIVED = "ARRIVED"
