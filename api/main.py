from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from core.graph import Graph, EdgeUpdate
from core.routing import time_dependent_dijkstra, a_star_route
import datetime
import os

app = FastAPI(title="Emergency Ambulance Routing - MVP")

@app.get("/")
def read_root():
    return {"message": "Emergency Ambulance Routing API is running!"}

# Load sample graph
GRAPH_PATH = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_graph.json")
graph = Graph()
if os.path.exists(GRAPH_PATH):
    graph.load_from_file(GRAPH_PATH)

# Schemas
class LatLon(BaseModel):
    lat: float
    lon: float

class RouteRequest(BaseModel):
    ambulance_id: Optional[str]
    current_location: LatLon
    destination: LatLon
    departure_time: Optional[datetime.datetime] = None
    constraints: Optional[dict] = {}

class RouteResponse(BaseModel):
    ambulance_id: Optional[str]
    total_time_minutes: float
    estimated_arrival: str
    route_steps: List[str]

class TrafficSnapshot(BaseModel):
    timestamp: datetime.datetime
    edge_updates: List[EdgeUpdate]

class RerouteCheck(BaseModel):
    ambulance_id: str
    current_time: datetime.datetime

active_routes = {}

# --- Endpoints ---

@app.post("/route_ambulance", response_model=RouteResponse)
def route_ambulance(req: RouteRequest):
    start_node = graph.nearest_node((req.current_location.lat, req.current_location.lon))
    end_node = graph.nearest_node((req.destination.lat, req.destination.lon))
    depart_time = req.departure_time or datetime.datetime.utcnow()

    arrival_time, path, per_segment_times = time_dependent_dijkstra(graph, start_node, end_node, depart_time)
    if path is None:
        raise HTTPException(status_code=404, detail="No route found")

    route_steps = []
    total_seconds = 0
    for i in range(len(path) - 1):
        eta_start, eta_end = per_segment_times[i]
        seconds = int((eta_end - eta_start).total_seconds())
        total_seconds += seconds
        start_coords = graph.nodes[path[i]]
        end_coords = graph.nodes[path[i + 1]]
        step = f"Go from ({start_coords['lat']},{start_coords['lon']}) to ({end_coords['lat']},{end_coords['lon']}) in {seconds // 60} min"
        route_steps.append(step)

    resp = {
        "ambulance_id": req.ambulance_id,
        "total_time_minutes": round(total_seconds / 60, 1),
        "estimated_arrival": arrival_time.strftime("%I:%M %p"),
        "route_steps": route_steps
    }

    if req.ambulance_id:
        active_routes[req.ambulance_id] = {
            "path": path,
            "current_lat": req.current_location.lat,
            "current_lon": req.current_location.lon,
            "destination_lat": req.destination.lat,
            "destination_lon": req.destination.lon,
            "eta": arrival_time
        }

    return resp


@app.post("/reroute_check")
def reroute_check(req: RerouteCheck):
    threshold_sec = 30
    old_route = active_routes.get(req.ambulance_id)
    if not old_route:
        return {"reroute": False, "message": "No active route found for this ambulance"}

    start_node = graph.nearest_node((old_route['current_lat'], old_route['current_lon']))
    end_node = graph.nearest_node((old_route['destination_lat'], old_route['destination_lon']))

    try:
        new_eta, new_path, _ = time_dependent_dijkstra(graph, start_node, end_node, req.current_time)
    except Exception:
        return {"reroute": False, "message": "Error computing alternative route"}

    if not new_path:
        return {"reroute": False, "message": "No alternative route found"}

    old_eta = old_route['eta']
    time_saved = int((old_eta - new_eta).total_seconds())

    if time_saved >= threshold_sec:
        old_path_names = [graph.nodes[n].get('name', str(n)) for n in old_route['path']]
        new_path_names = [graph.nodes[n].get('name', str(n)) for n in new_path]
        return {
            "reroute": True,
            "message": f"Rerouting recommended! You save {time_saved // 60} min {time_saved % 60} sec.",
            "old_path": old_path_names,
            "new_path": new_path_names,
            "old_eta_minutes": int((old_eta - datetime.datetime.utcnow()).total_seconds() // 60),
            "new_eta_minutes": int((new_eta - datetime.datetime.utcnow()).total_seconds() // 60),
            "time_saved_seconds": time_saved
        }
    else:
        return {"reroute": False, "message": "ETA improvement below threshold, continue current route"}


@app.post("/traffic_snapshot")
def traffic_snapshot(snapshot: TrafficSnapshot):
    applied = 0
    for e in snapshot.edge_updates:
        if e.edge_id in graph.edges:
            graph.apply_edge_update(e)
            applied += 1
    return {"status": "ok", "applied": applied}


@app.post("/route_ambulance_astar", response_model=RouteResponse)
def route_ambulance_astar(req: RouteRequest):
    start_node = graph.nearest_node((req.current_location.lat, req.current_location.lon))
    end_node = graph.nearest_node((req.destination.lat, req.destination.lon))
    depart_time = req.departure_time or datetime.datetime.utcnow()

    # For MVP, a_star_route returns dijkstra-style output
    arrival_time, path, per_segment_times = a_star_route(graph, start_node, end_node, depart_time)
    if path is None:
        raise HTTPException(status_code=404, detail="No route found")

    route_steps = []
    total_seconds = 0
    for i in range(len(path) - 1):
        eid = graph.edge_id_between(path[i], path[i + 1])
        step_seconds = int(graph.edge_travel_time(eid, depart_time.timestamp()))
        total_seconds += step_seconds
        start_coords = graph.nodes[path[i]]
        end_coords = graph.nodes[path[i + 1]]
        step = f"Go from ({start_coords['lat']},{start_coords['lon']}) to ({end_coords['lat']},{end_coords['lon']}) in {step_seconds // 60} min"
        route_steps.append(step)
        depart_time += datetime.timedelta(seconds=step_seconds)

    arrival_time = depart_time

    return {
        "ambulance_id": req.ambulance_id,
        "total_time_minutes": round(total_seconds / 60, 1),
        "estimated_arrival": arrival_time.strftime("%I:%M %p"),
        "route_steps": route_steps
    }