from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Tuple, Dict, Any
from core.graph import Graph, EdgeUpdate
from core.routing import time_dependent_dijkstra, a_star_route
import datetime
from datetime import timezone
import pytz
IST = pytz.timezone("Asia/Kolkata")
import os

app = FastAPI(title="Emergency Ambulance Routing - MVP (fixed reroute_check)")

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
    constraints: Optional[dict] = None
class TimeDuration(BaseModel):
    minutes: int
    seconds: int

class RouteResponse(BaseModel):
    ambulance_id: Optional[str]
    total_time_minutes: TimeDuration
    estimated_arrival: str
    route_steps: List[str]

class TrafficSnapshot(BaseModel):
    timestamp: datetime.datetime
    edge_updates: List[EdgeUpdate]

class RerouteCheck(BaseModel):
    ambulance_id: str
# Active routes store enhanced data:
# {
#   ambulance_id: {
#       'path': [node,...],
#       'per_segment_times': [(eta_start, eta_end), ...],
#       'departure_time': datetime,
#       'eta': datetime,  # final eta
#       'last_known_lat': float,
#       'last_known_lon': float,
#   }
# }
active_routes: Dict[str, Dict[str, Any]] = {}

# Utility: find where along the path the ambulance is at given time
def estimate_progress(per_segment_times: List[Tuple[datetime.datetime, datetime.datetime]], now: datetime.datetime) -> Tuple[int, datetime.datetime]:
    """
    Returns (current_segment_index, segment_start_time)
    segment_index is the index of the segment ambulance is currently on (0-based for edge between node[i] -> node[i+1]).
    If now is before first segment start, returns (0, first_start).
    If now is after last segment end, returns (len(per_segment_times)-1, last_start)
    """
    if not per_segment_times:
        return 0, now
    for i, (s, e) in enumerate(per_segment_times):
        if s <= now <= e:
            return i, s
    # not inside any: before start or after end
    if now < per_segment_times[0][0]:
        return 0, per_segment_times[0][0]
    return len(per_segment_times) - 1, per_segment_times[-1][0]

# --- Endpoints ---
@app.get("/")
def read_root():
    return {"message": "Emergency Ambulance Routing API (fixed reroute_check) is running!"}

@app.post("/route_ambulance", response_model=RouteResponse)
def route_ambulance(req: RouteRequest):
    start_node = graph.nearest_node((req.current_location.lat, req.current_location.lon))
    end_node = graph.nearest_node((req.destination.lat, req.destination.lon))
    depart_time = datetime.datetime.now(IST).replace(tzinfo=None)




    arrival_time, path, per_segment_times = time_dependent_dijkstra(graph, start_node, end_node, depart_time)
    if path is None:
        raise HTTPException(status_code=404, detail="No route found")

    route_steps: List[str] = []
    total_seconds = 0
    for i in range(len(path) - 1):
        eta_start, eta_end = per_segment_times[i]
        seconds = int((eta_end - eta_start).total_seconds())
        total_seconds += seconds
        start_coords = graph.nodes[path[i]]
        end_coords = graph.nodes[path[i + 1]]
        step = f"Go from ({start_coords['lat']},{start_coords['lon']}) to ({end_coords['lat']},{end_coords['lon']}) in {seconds // 60} min {seconds % 60} sec"
        route_steps.append(step)
    arrival_time_ist = IST.localize(arrival_time)


    resp = {
    "ambulance_id": req.ambulance_id,
    "total_time_minutes": {
        "minutes": total_seconds // 60,
        "seconds": total_seconds % 60
    },
    "estimated_arrival": arrival_time_ist.strftime("%I:%M:%S %p"),
    "route_steps": route_steps
    }   



    if req.ambulance_id:
        # store enhanced route info so reroute_check can reason about progress
        active_routes[req.ambulance_id] = {
            "path": path,
            "per_segment_times": per_segment_times,
            "departure_time": depart_time,
            "eta": arrival_time,
            "last_known_lat": req.current_location.lat,
            "last_known_lon": req.current_location.lon,
        }

    return resp

@app.post("/reroute_check")
def reroute_check(req: RerouteCheck):
    threshold_sec = 120  # 2 minutes

    old_route = active_routes.get(req.ambulance_id)
    if not old_route:
        return {"reroute": False, "message": "No active route found for this ambulance"}

    per_segment_times: List[Tuple[datetime.datetime, datetime.datetime]] = old_route.get("per_segment_times", [])
    path: List[Any] = old_route.get("path", [])
    old_eta: datetime.datetime = old_route.get("eta")

    # ALWAYS use server current local time (IST on your machine), naive
    now = datetime.datetime.now().replace(tzinfo=None)

    # Estimate current position on old path
    seg_idx, _ = estimate_progress(per_segment_times, now)

    # Decide current node (approximation: next node)
    if 0 <= seg_idx < len(path) - 1:
        current_node = path[seg_idx + 1]
    else:
        current_node = path[-1]

    dest_node = path[-1]
    if not dest_node:
        return {"reroute": False, "message": "Unknown destination for this active route"}

    # Compute alternative route from CURRENT position
    try:
        new_eta, new_path, new_per_segment_times = time_dependent_dijkstra(
            graph, current_node, dest_node, now
        )
    except Exception as e:
        return {"reroute": False, "message": f"Error computing alternative route: {e}"}

    if not new_path:
        return {"reroute": False, "message": "No alternative route found"}

    # Remaining times (seconds)
    old_remaining_seconds = max(
        0, int((old_eta - now).total_seconds())
    )
    new_remaining_seconds = max(
        0, int((new_eta - now).total_seconds())
    )

    time_saved = old_remaining_seconds - new_remaining_seconds

    # --- Slowdown detection on upcoming edges ---
    slowdown_detected = False
    slowdown_msg = ""
    max_inspect = 3

    for look_ahead in range(min(max_inspect, len(path) - (seg_idx + 1))):
        u = path[seg_idx + 1 + look_ahead]
        v = path[seg_idx + 2 + look_ahead] if (seg_idx + 2 + look_ahead) < len(path) else None
        if v is None:
            break

        eid = graph.edge_id_between(u, v)
        if not eid:
            continue

        try:
            current_tt = graph.edge_travel_time(eid, now.timestamp())

            # Use original planned segment duration as baseline
            base_start, base_end = per_segment_times[seg_idx + look_ahead]
            baseline_tt = (base_end - base_start).total_seconds()

            if baseline_tt > 0 and current_tt / baseline_tt > 1.5:
                slowdown_detected = True
                slowdown_msg = (
                    f"Traffic slowdown ahead on edge {eid}: "
                    f"{int(baseline_tt)}s → {int(current_tt)}s"
                )
                break
        except Exception:
            pass

    # --- Reroute decision ---
    if time_saved >= threshold_sec or slowdown_detected:
        old_path_names = [graph.nodes[n].get("name", str(n)) for n in path]
        new_path_names = [graph.nodes[n].get("name", str(n)) for n in new_path]

        return {
            "reroute": True,
            "reason": "Better route found" if time_saved >= threshold_sec else "Traffic slowdown detected",
            "time_saved": {
                "minutes": max(0, time_saved // 60),
                "seconds": max(0, time_saved % 60)
            },
            "old_remaining_time": {
                "minutes": old_remaining_seconds // 60,
                "seconds": old_remaining_seconds % 60
            },
            "new_remaining_time": {
                "minutes": new_remaining_seconds // 60,
                "seconds": new_remaining_seconds % 60
            },
            "old_path": old_path_names,
            "new_path": new_path_names,
            "details": slowdown_msg
        }

    return {
        "reroute": False,
        "message": "ETA improvement below threshold and no major slowdowns detected"
    }

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
        step = f"Go from ({start_coords['lat']},{start_coords['lon']}) to ({end_coords['lat']},{end_coords['lon']}) in {step_seconds // 60} min {step_seconds % 60} sec"
        route_steps.append(step)
        depart_time += datetime.timedelta(seconds=step_seconds)

    arrival_time_ist = arrival_time.replace(tzinfo=pytz.utc).astimezone(IST)

    return {
        "ambulance_id": req.ambulance_id,
        "total_time_minutes": {
            "minutes": total_seconds // 60,
            "seconds": total_seconds % 60
        },
        "estimated_arrival": arrival_time_ist.strftime("%I:%M:%S %p"),
        "route_steps": route_steps
    }
