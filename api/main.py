from fastapi import FastAPI, HTTPException
from .schemas import RerouteCheck
from pydantic import BaseModel
from typing import Dict, List, Optional
from core.graph import Graph, EdgeUpdate
from core.routing import time_dependent_dijkstra, dijkstra_route
import datetime
import uuid
import json
import os

app = FastAPI(title="Emergency Ambulance Routing - MVP")

@app.get("/")
def read_root():
    return {"message": "Emergency Ambulance Routing API is running!"}

# Load sample graph at startup
GRAPH_PATH = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_graph.json")
graph = Graph()
if os.path.exists(GRAPH_PATH):
    graph.load_from_file(GRAPH_PATH)

class LatLon(BaseModel):
    lat: float
    lon: float

class RouteRequest(BaseModel):
    ambulance_id: Optional[str]
    current_location: LatLon
    destination: LatLon
    departure_time: Optional[datetime.datetime] = None
    constraints: Optional[dict] = {}

class RouteSegment(BaseModel):
    edge_id: int
    start_node: int
    end_node: int
    eta_start: datetime.datetime
    eta_end: datetime.datetime

class RouteResponse(BaseModel):
    ambulance_id: Optional[str]
    total_time_minutes: float
    estimated_arrival: str
    route_steps: List[str]

class TrafficSnapshot(BaseModel):
    timestamp: datetime.datetime
    edge_updates: List[EdgeUpdate]

@app.post("/route_ambulance", response_model=RouteResponse)
def route_ambulance(req: RouteRequest):
    # Map lat/lon to nearest node
    start_node = graph.nearest_node((req.current_location.lat, req.current_location.lon))
    end_node = graph.nearest_node((req.destination.lat, req.destination.lon))
    depart_time = req.departure_time or datetime.datetime.utcnow()

    # Use time-dependent algorithm
    arrival_time, path, per_segment_times = time_dependent_dijkstra(graph, start_node, end_node, depart_time)

    if path is None:
        raise HTTPException(status_code=404, detail="No route found")

    segments = []
    route_steps = []
    total_seconds = 0

    for i in range(len(path)-1):
        eta_start, eta_end = per_segment_times[i]
        seconds = int((eta_end - eta_start).total_seconds())
        total_seconds += seconds
        start_coords = graph.nodes[path[i]]
        end_coords = graph.nodes[path[i+1]]
        step = f"Go from ({start_coords['lat']},{start_coords['lon']}) to ({end_coords['lat']},{end_coords['lon']}) in {seconds//60} min"
        route_steps.append(step)

    resp = {
        "ambulance_id": req.ambulance_id,
        "total_time_minutes": round(total_seconds / 60, 1),
        "estimated_arrival": arrival_time.strftime("%I:%M %p"),
        "route_steps": route_steps
    }
    return resp

@app.post("/traffic_snapshot")
def traffic_snapshot(snapshot: TrafficSnapshot):
    # Apply traffic updates
    for e in snapshot.edge_updates:
        graph.apply_edge_update(e)
    return {"status": "ok", "applied": len(snapshot.edge_updates)}

@app.post("/reroute_check")
def reroute_check(req: RerouteCheck):
    # Human-readable reroute info (example)
    old_eta_minutes = 500 / 60
    new_eta_minutes = 470 / 60
    return {
        "reroute_needed": True,
        "old_route": ["A -> B -> D -> E ({:.1f} min)".format(old_eta_minutes)],
        "new_route": ["A -> C -> D -> E ({:.1f} min)".format(new_eta_minutes)],
        "time_saved_minutes": round(old_eta_minutes - new_eta_minutes, 1)
    }
