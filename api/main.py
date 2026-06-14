"""
Emergency Ambulance Routing API — FastAPI application entry point.

Startup:
    PYTHONPATH=. uvicorn api.main:app --reload

All routing logic lives in core/. This module wires up HTTP endpoints,
middleware, and application state.
"""

import datetime
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.schemas import (
    PositionUpdate,
    RerouteCheck,
    RouteRequest,
    RouteResponse,
    RouteStatus,
    TrafficSnapshot,
)
from core.config import (
    APP_ENV,
    GRAPH_PATH,
    LOG_LEVEL,
    REROUTE_THRESHOLD_SEC,
    SLOWDOWN_LOOKAHEAD,
    SLOWDOWN_RATIO,
)
from core.graph import EdgeNotFoundError, Graph
from core.logging_config import configure_logging, get_logger
from core.routing import _ensure_utc, _remaining_seconds, a_star_route, time_dependent_dijkstra

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

configure_logging(level=LOG_LEVEL, env=APP_ENV)
log = get_logger("api")

UTC = datetime.timezone.utc

# ---------------------------------------------------------------------------
# Graph initialisation
# ---------------------------------------------------------------------------

_default_graph_path = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_graph.json")
_graph_path = GRAPH_PATH or _default_graph_path

graph = Graph()
if os.path.exists(_graph_path):
    graph.load_from_file(_graph_path)
    log.info("Graph loaded: %d nodes, %d edges", len(graph.nodes), len(graph.edges))
else:
    log.warning("Graph file not found at %s — starting with empty graph", _graph_path)

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Emergency Ambulance Routing System",
    description=(
        "Real-time ambulance routing with time-dependent Dijkstra and A*, "
        "dynamic traffic updates, and automatic rerouting."
    ),
    version="1.0.0",
    contact={
        "name": "ChikatlaRakesh",
        "url": "https://github.com/chikatlarakesh/ambulance-routing",
    },
    license_info={"name": "MIT"},
    openapi_tags=[
        {"name": "routing", "description": "Route an ambulance using Dijkstra or A*"},
        {"name": "traffic", "description": "Apply real-time traffic updates and trigger rerouting"},
        {
            "name": "debug",
            "description": "Inspect graph state and active routes (non-production use)",
        },
    ],
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
)

# ---------------------------------------------------------------------------
# Request ID + timing middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.perf_counter()

    log.info(
        "Incoming request: %s %s request_id=%s",
        request.method,
        request.url.path,
        request_id,
    )

    try:
        response: Response = await call_next(request)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        log.error(
            "Unhandled exception: %s request_id=%s elapsed_ms=%.1f",
            exc,
            request_id,
            elapsed_ms,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers={"X-Request-ID": request_id},
        )

    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"

    log.info(
        "Response: %d %s %s %.1f ms",
        response.status_code,
        request.method,
        request.url.path,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Active route storage
# ---------------------------------------------------------------------------

active_routes: Dict[str, Dict[str, Any]] = {}
reroute_events: List[Dict[str, Any]] = []

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(tz=UTC)


def _store_route(
    ambulance_id: str,
    path: List[int],
    per_segment_times: List[Tuple[datetime.datetime, datetime.datetime]],
    departure_time: datetime.datetime,
    eta: datetime.datetime,
    start_lat: float,
    start_lon: float,
    status: RouteStatus = RouteStatus.EN_ROUTE,
) -> None:
    now = _now_utc()
    active_routes[ambulance_id] = {
        "ambulance_id": ambulance_id,
        "path": path,
        "per_segment_times": per_segment_times,
        "departure_time": departure_time,
        "route_start_time": departure_time,
        "current_segment_index": 0,
        "current_node": path[0] if path else None,
        "current_lat": start_lat,
        "current_lon": start_lon,
        "eta": eta,
        "remaining_seconds": _remaining_seconds(eta, now),
        "status": status,
        "last_update_time": now,
    }


def _estimate_segment(
    per_segment_times: List[Tuple[datetime.datetime, datetime.datetime]],
    now: datetime.datetime,
) -> Tuple[int, datetime.datetime]:
    """Return (segment_index, segment_start_time) for the ambulance's current position."""
    if not per_segment_times:
        return 0, now
    for i, (s, e) in enumerate(per_segment_times):
        if s <= now <= e:
            return i, s
    if now < per_segment_times[0][0]:
        return 0, per_segment_times[0][0]
    return len(per_segment_times) - 1, per_segment_times[-1][0]


def _build_route_steps(
    g: Graph, path: List[int], per_segment_times: List[Tuple[datetime.datetime, datetime.datetime]]
) -> Tuple[List[str], int]:
    steps = []
    total_seconds = 0
    for i in range(len(path) - 1):
        s_dt, e_dt = per_segment_times[i]
        secs = int((e_dt - s_dt).total_seconds())
        total_seconds += secs
        sc = g.nodes[path[i]]
        ec = g.nodes[path[i + 1]]
        steps.append(
            f"Node {path[i]} ({sc['lat']:.4f},{sc['lon']:.4f}) → "
            f"Node {path[i + 1]} ({ec['lat']:.4f},{ec['lon']:.4f}) "
            f"in {secs // 60}m {secs % 60}s"
        )
    return steps, total_seconds


def _compute_remaining_path_cost(
    g: Graph,
    path: List[int],
    from_node_idx: int,
    now: datetime.datetime,
) -> float:
    """Sum edge travel times from path[from_node_idx] to path[-1] using current graph state."""
    total = 0.0
    t = now.timestamp()
    for i in range(from_node_idx, len(path) - 1):
        eid = g.edge_id_between(path[i], path[i + 1])
        if eid is None:
            return float("inf")
        cost = g.edge_travel_time(eid, t)
        total += cost
        t += cost
    return total


def _recalculate_eta(
    g: Graph,
    ambulance_id: str,
    now: Optional[datetime.datetime] = None,
    algorithm: str = "dijkstra",
) -> Optional[Dict[str, Any]]:
    """
    Recalculate the best route from the ambulance's estimated current position.
    Returns a result dict or None if the ambulance has no active route.
    """
    route = active_routes.get(ambulance_id)
    if not route:
        return None
    if route["status"] == RouteStatus.ARRIVED:
        return None

    now = now or _now_utc()
    per_seg = route["per_segment_times"]
    path = route["path"]

    seg_idx, _ = _estimate_segment(per_seg, now)
    if now < per_seg[0][0]:
        current_node_idx = 0
    else:
        current_node_idx = min(seg_idx + 1, len(path) - 2)
    current_node = path[current_node_idx]
    dest_node = path[-1]

    fn = time_dependent_dijkstra if algorithm == "dijkstra" else a_star_route
    new_eta, new_path, new_per_seg = fn(g, current_node, dest_node, now)

    if new_path is None:
        return None

    old_remaining = _compute_remaining_path_cost(g, path, current_node_idx, now)
    new_remaining = _remaining_seconds(new_eta, now)
    time_saved = old_remaining - new_remaining

    return {
        "new_eta": new_eta,
        "new_path": new_path,
        "new_per_seg": new_per_seg,
        "old_remaining": old_remaining,
        "new_remaining": new_remaining,
        "time_saved": time_saved,
        "current_node": current_node,
    }


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@app.get(
    "/",
    summary="Health check",
    description="Returns API status and loaded graph statistics.",
    tags=["routing"],
)
def read_root():
    return {
        "message": "Emergency Ambulance Routing API is running",
        "version": "1.0.0",
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "active_ambulances": len(active_routes),
    }


# ---------------------------------------------------------------------------
# Routing endpoints  (/api/v1/ + legacy root aliases)
# ---------------------------------------------------------------------------


def _do_route(req: RouteRequest, algorithm: str) -> Dict[str, Any]:
    start_node = graph.nearest_node((req.current_location.lat, req.current_location.lon))
    end_node = graph.nearest_node((req.destination.lat, req.destination.lon))
    depart_dt = _ensure_utc(req.departure_time) if req.departure_time else _now_utc()

    fn = time_dependent_dijkstra if algorithm == "dijkstra" else a_star_route
    arrival, path, per_seg = fn(graph, start_node, end_node, depart_dt)

    if path is None:
        log.warning(
            "No route found: start=%d end=%d algorithm=%s ambulance_id=%s",
            start_node,
            end_node,
            algorithm,
            req.ambulance_id,
        )
        raise HTTPException(status_code=404, detail="No route found between the given locations")

    steps, total_sec = _build_route_steps(graph, path, per_seg)

    if req.ambulance_id:
        _store_route(
            req.ambulance_id,
            path,
            per_seg,
            depart_dt,
            arrival,
            req.current_location.lat,
            req.current_location.lon,
        )
        log.info(
            "Route stored: ambulance_id=%s algorithm=%s path=%s eta=%s",
            req.ambulance_id,
            algorithm,
            path,
            arrival.isoformat(),
        )

    return {
        "ambulance_id": req.ambulance_id,
        "algorithm": algorithm,
        "total_time_minutes": {"minutes": total_sec // 60, "seconds": total_sec % 60},
        "estimated_arrival": arrival.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "route_steps": steps,
        "path": path,
    }


@app.post(
    "/api/v1/route_ambulance",
    response_model=RouteResponse,
    summary="Route ambulance (Dijkstra)",
    description=(
        "Calculate the fastest route using time-dependent Dijkstra. "
        "Stores the route for automatic rerouting when traffic changes."
    ),
    tags=["routing"],
    responses={
        200: {"description": "Route calculated successfully"},
        404: {"description": "No route found between the given locations"},
        422: {"description": "Validation error in request body"},
    },
)
def route_ambulance_v1(req: RouteRequest):
    return _do_route(req, "dijkstra")


@app.post(
    "/api/v1/route_ambulance_astar",
    response_model=RouteResponse,
    summary="Route ambulance (A*)",
    description=(
        "Calculate the fastest route using time-dependent A* with haversine heuristic. "
        "Returns identical ETA to Dijkstra on the same graph; generally faster on large sparse graphs."
    ),
    tags=["routing"],
    responses={
        200: {"description": "Route calculated successfully"},
        404: {"description": "No route found between the given locations"},
        422: {"description": "Validation error in request body"},
    },
)
def route_ambulance_astar_v1(req: RouteRequest):
    return _do_route(req, "astar")


@app.post(
    "/api/v1/traffic_snapshot",
    summary="Apply traffic update",
    description=(
        "Apply one or more edge weight updates (multiplier or absolute override). "
        "Automatically evaluates all active ambulances for rerouting."
    ),
    tags=["traffic"],
    responses={
        200: {"description": "Updates applied; auto-reroute results included"},
        422: {"description": "Validation error"},
    },
)
def traffic_snapshot_v1(snapshot: TrafficSnapshot):
    applied = []
    errors = []
    for e in snapshot.edge_updates:
        try:
            graph.apply_edge_update(e)
            applied.append(e.edge_id)
            log.debug(
                "Traffic update applied: edge_id=%d multiplier=%s absolute_time=%s",
                e.edge_id,
                e.multiplier,
                e.absolute_time,
            )
        except EdgeNotFoundError as ex:
            errors.append(str(ex))
            log.warning("Traffic update failed: %s", ex)

    log.info("Traffic snapshot processed: applied=%s errors=%d", applied, len(errors))

    auto_reroutes = []
    now = _now_utc()
    for amb_id, route in list(active_routes.items()):
        if route["status"] == RouteStatus.ARRIVED:
            continue
        result = _recalculate_eta(graph, amb_id, now)
        if result is None:
            continue
        if result["time_saved"] >= REROUTE_THRESHOLD_SEC:
            old_path = route["path"]
            route["path"] = [result["current_node"]] + result["new_path"]
            route["per_segment_times"] = result["new_per_seg"]
            route["eta"] = result["new_eta"]
            route["remaining_seconds"] = result["new_remaining"]
            route["status"] = RouteStatus.REROUTED
            route["last_update_time"] = now

            event = {
                "ambulance_id": amb_id,
                "timestamp": now.isoformat(),
                "old_path": old_path,
                "new_path": route["path"],
                "time_saved_sec": result["time_saved"],
                "new_eta": result["new_eta"].isoformat(),
            }
            reroute_events.append(event)
            auto_reroutes.append(event)
            log.info(
                "Auto-reroute triggered: ambulance_id=%s time_saved=%.0fs new_path=%s",
                amb_id,
                result["time_saved"],
                route["path"],
            )
        else:
            route["remaining_seconds"] = result["old_remaining"]
            route["eta"] = now + datetime.timedelta(seconds=result["old_remaining"])
            route["last_update_time"] = now

    return {
        "status": "ok",
        "applied_edge_ids": applied,
        "errors": errors,
        "auto_reroutes": auto_reroutes,
    }


@app.post(
    "/api/v1/reroute_check",
    summary="Manual reroute evaluation",
    description=(
        "Evaluate whether a specific ambulance should be rerouted based on current traffic. "
        "Triggers reroute if time saving exceeds threshold or a major slowdown is detected."
    ),
    tags=["traffic"],
    responses={
        200: {"description": "Reroute decision returned"},
        404: {"description": "No active route for the given ambulance_id"},
    },
)
def reroute_check_v1(req: RerouteCheck):
    old_route = active_routes.get(req.ambulance_id)
    if not old_route:
        raise HTTPException(
            status_code=404,
            detail=f"No active route for ambulance {req.ambulance_id}",
        )

    now = _now_utc()
    result = _recalculate_eta(graph, req.ambulance_id, now)
    if result is None:
        return {"reroute": False, "message": "Could not compute alternative route"}

    path = old_route["path"]
    per_seg = old_route["per_segment_times"]
    seg_idx, _ = _estimate_segment(per_seg, now)

    slowdown_detected = False
    slowdown_msg = ""
    for look_ahead in range(min(SLOWDOWN_LOOKAHEAD, len(path) - seg_idx - 2)):
        u = path[seg_idx + 1 + look_ahead]
        v_idx = seg_idx + 2 + look_ahead
        if v_idx >= len(path):
            break
        v = path[v_idx]
        eid = graph.edge_id_between(u, v)
        if not eid:
            continue
        try:
            current_tt = graph.edge_travel_time(eid, now.timestamp())
            base_start, base_end = per_seg[seg_idx + 1 + look_ahead]
            baseline_tt = (base_end - base_start).total_seconds()
            if baseline_tt > 0 and current_tt / baseline_tt > SLOWDOWN_RATIO:
                slowdown_detected = True
                slowdown_msg = (
                    f"Slowdown on edge {eid} (node {u}->{v}): "
                    f"{int(baseline_tt)}s -> {int(current_tt)}s"
                )
                log.info("Slowdown detected: %s", slowdown_msg)
                break
        except Exception:
            pass

    should_reroute = result["time_saved"] >= REROUTE_THRESHOLD_SEC or slowdown_detected

    if should_reroute:
        old_path = old_route["path"]
        old_route["path"] = [result["current_node"]] + result["new_path"]
        old_route["per_segment_times"] = result["new_per_seg"]
        old_route["eta"] = result["new_eta"]
        old_route["remaining_seconds"] = result["new_remaining"]
        old_route["status"] = RouteStatus.REROUTED
        old_route["last_update_time"] = now

        saved_sec = int(result["time_saved"])
        event = {
            "ambulance_id": req.ambulance_id,
            "timestamp": now.isoformat(),
            "old_path": old_path,
            "new_path": old_route["path"],
            "time_saved_sec": result["time_saved"],
            "new_eta": result["new_eta"].isoformat(),
        }
        reroute_events.append(event)
        log.info(
            "Reroute applied: ambulance_id=%s reason=%s time_saved=%ds",
            req.ambulance_id,
            "time_saving" if result["time_saved"] >= REROUTE_THRESHOLD_SEC else "slowdown",
            saved_sec,
        )

        old_n = [graph.nodes[n].get("name", str(n)) for n in old_path]
        new_n = [graph.nodes[n].get("name", str(n)) for n in old_route["path"]]
        return {
            "reroute": True,
            "reason": (
                "Better route found"
                if result["time_saved"] >= REROUTE_THRESHOLD_SEC
                else "Slowdown detected"
            ),
            "time_saved": {"minutes": saved_sec // 60, "seconds": saved_sec % 60},
            "old_remaining": {
                "minutes": int(result["old_remaining"]) // 60,
                "seconds": int(result["old_remaining"]) % 60,
            },
            "new_remaining": {
                "minutes": int(result["new_remaining"]) // 60,
                "seconds": int(result["new_remaining"]) % 60,
            },
            "old_path": old_n,
            "new_path": new_n,
            "slowdown_details": slowdown_msg,
        }

    return {
        "reroute": False,
        "time_saved_sec": result["time_saved"],
        "old_remaining_sec": result["old_remaining"],
        "new_remaining_sec": result["new_remaining"],
        "message": "ETA improvement below threshold and no major slowdowns detected",
    }


@app.post(
    "/api/v1/update_position",
    summary="Update ambulance position",
    description="Report current GPS position for an active ambulance. Updates estimated segment and remaining time.",
    tags=["routing"],
    responses={
        200: {"description": "Position updated"},
        404: {"description": "No active route for the given ambulance_id"},
    },
)
def update_position_v1(update: PositionUpdate):
    route = active_routes.get(update.ambulance_id)
    if not route:
        raise HTTPException(
            status_code=404,
            detail=f"No active route for ambulance {update.ambulance_id}",
        )

    ts = _ensure_utc(update.timestamp) if update.timestamp else _now_utc()
    nearest = graph.nearest_node((update.lat, update.lon))
    seg_idx, _ = _estimate_segment(route["per_segment_times"], ts)

    path = route["path"]
    per_seg_t = route["per_segment_times"]
    if ts < per_seg_t[0][0]:
        node_idx = 0
    else:
        node_idx = min(seg_idx + 1, len(path) - 2)

    route["current_lat"] = update.lat
    route["current_lon"] = update.lon
    route["current_node"] = nearest
    route["current_segment_index"] = seg_idx
    route["last_update_time"] = ts
    route["remaining_seconds"] = _compute_remaining_path_cost(graph, path, node_idx, ts)

    dest_node = route["path"][-1]
    if nearest == dest_node or route["remaining_seconds"] == 0:
        route["status"] = RouteStatus.ARRIVED
        log.info("Ambulance arrived: ambulance_id=%s", update.ambulance_id)

    log.debug(
        "Position updated: ambulance_id=%s node=%d remaining=%.0fs",
        update.ambulance_id,
        nearest,
        route["remaining_seconds"],
    )

    return {
        "ambulance_id": update.ambulance_id,
        "status": route["status"],
        "current_node": nearest,
        "remaining_seconds": route["remaining_seconds"],
        "eta": _ensure_utc(route["eta"]).isoformat(),
    }


# ---------------------------------------------------------------------------
# Debug endpoints  (/api/v1/debug/ + legacy aliases)
# ---------------------------------------------------------------------------


@app.get(
    "/api/v1/debug/edges",
    summary="Dump graph state",
    description="Returns all nodes and edges with current multipliers and overrides. Non-production use.",
    tags=["debug"],
)
def debug_edges_v1():
    return graph.graph_to_dict()


@app.get(
    "/api/v1/debug/active_routes",
    summary="List active routes",
    description="Returns all tracked ambulances and their current state.",
    tags=["debug"],
)
def debug_active_routes_v1():
    result = {}
    for amb_id, r in active_routes.items():
        result[amb_id] = {
            "ambulance_id": amb_id,
            "path": r["path"],
            "status": r["status"],
            "current_node": r["current_node"],
            "current_lat": r["current_lat"],
            "current_lon": r["current_lon"],
            "eta": _ensure_utc(r["eta"]).isoformat(),
            "remaining_seconds": r["remaining_seconds"],
            "last_update_time": _ensure_utc(r["last_update_time"]).isoformat(),
        }
    return result


@app.post(
    "/api/v1/debug/reset_overrides",
    summary="Reset edge overrides",
    description="Reset absolute_time and multiplier overrides for one edge (by edge_id query param) or all edges.",
    tags=["debug"],
)
def debug_reset_overrides_v1(edge_id: Optional[int] = None):
    graph.reset_edge_overrides(edge_id)
    log.info("Edge overrides reset: edge_id=%s", edge_id or "all")
    return {"status": "ok", "reset_edge_id": edge_id or "all"}


@app.get(
    "/api/v1/debug/reroute_events",
    summary="Reroute event history",
    description="Returns the full history of reroute events since the server started.",
    tags=["debug"],
)
def debug_reroute_events_v1():
    return {"events": reroute_events}


# ---------------------------------------------------------------------------
# Legacy root-level aliases (backward compatibility — no breaking changes)
# ---------------------------------------------------------------------------


@app.post("/route_ambulance", response_model=RouteResponse, include_in_schema=False)
def route_ambulance(req: RouteRequest):
    return route_ambulance_v1(req)


@app.post("/route_ambulance_astar", response_model=RouteResponse, include_in_schema=False)
def route_ambulance_astar(req: RouteRequest):
    return route_ambulance_astar_v1(req)


@app.post("/traffic_snapshot", include_in_schema=False)
def traffic_snapshot(snapshot: TrafficSnapshot):
    return traffic_snapshot_v1(snapshot)


@app.post("/reroute_check", include_in_schema=False)
def reroute_check(req: RerouteCheck):
    return reroute_check_v1(req)


@app.post("/update_position", include_in_schema=False)
def update_position(update: PositionUpdate):
    return update_position_v1(update)


@app.get("/debug/edges", include_in_schema=False)
def debug_edges():
    return debug_edges_v1()


@app.get("/debug/active_routes", include_in_schema=False)
def debug_active_routes():
    return debug_active_routes_v1()


@app.post("/debug/reset_overrides", include_in_schema=False)
def debug_reset_overrides(edge_id: Optional[int] = None):
    return debug_reset_overrides_v1(edge_id)


@app.get("/debug/reroute_events", include_in_schema=False)
def debug_reroute_events():
    return debug_reroute_events_v1()
