import datetime
import heapq
import math
from typing import List, Optional, Tuple

from core.config import A_STAR_MAX_SPEED_MS

UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------


def _ensure_utc(dt) -> datetime.datetime:
    """
    Accept a datetime, ISO-8601 string, or epoch float/int.
    Always return a timezone-aware UTC datetime.
    """
    if isinstance(dt, (int, float)):
        return datetime.datetime.fromtimestamp(dt, tz=UTC)
    if isinstance(dt, str):
        # Handle trailing Z
        dt = dt.replace("Z", "+00:00")
        parsed = datetime.datetime.fromisoformat(dt)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    if isinstance(dt, datetime.datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    raise TypeError(f"Cannot convert {type(dt)} to UTC datetime")


def _remaining_seconds(eta: datetime.datetime, now: datetime.datetime) -> float:
    """Return max(0, eta - now) in seconds. Both should be UTC-aware."""
    eta = _ensure_utc(eta)
    now = _ensure_utc(now)
    return max(0.0, (eta - now).total_seconds())


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Dijkstra (true time-dependent label-setting)
# ---------------------------------------------------------------------------


def dijkstra_route(
    graph,
    source: int,
    target: int,
    depart_time_dt,
) -> Tuple[
    Optional[datetime.datetime],
    Optional[List[int]],
    Optional[List[Tuple[datetime.datetime, datetime.datetime]]],
]:
    """
    Time-dependent Dijkstra.

    At each relaxation the edge cost is evaluated at the arrival time at that
    node, not at the global departure time — this is the correct FIFO
    time-dependent label-setting algorithm.

    Returns (arrival_dt_utc, path, per_segment_times)
    where per_segment_times is a list of (start_utc, end_utc) tuples.
    """
    depart_dt = _ensure_utc(depart_time_dt)
    start_ts = depart_dt.timestamp()

    dist: dict = {source: start_ts}
    prev: dict = {}
    pq = [(start_ts, source)]

    while pq:
        curr_ts, u = heapq.heappop(pq)
        if u == target:
            break
        if curr_ts > dist.get(u, 1e18):
            continue
        for v, eid in graph.neighbors(u):
            travel = graph.edge_travel_time(eid, curr_ts)
            arrival = curr_ts + travel
            if arrival < dist.get(v, 1e18):
                dist[v] = arrival
                prev[v] = u
                heapq.heappush(pq, (arrival, v))

    if target not in dist:
        return None, None, None

    path = _reconstruct_path(prev, source, target)
    per_seg = _build_segments(graph, path, start_ts)
    arrival_dt = datetime.datetime.fromtimestamp(dist[target], tz=UTC)
    return arrival_dt, path, per_seg


# Alias — exposed publicly so callers that want explicit time-dependence
# use this name; the implementation IS time-dependent.
def time_dependent_dijkstra(graph, source, target, depart_time_dt):
    return dijkstra_route(graph, source, target, depart_time_dt)


# ---------------------------------------------------------------------------
# A*
# ---------------------------------------------------------------------------


def a_star_route(
    graph,
    source: int,
    target: int,
    depart_time_dt,
) -> Tuple[
    Optional[datetime.datetime],
    Optional[List[int]],
    Optional[List[Tuple[datetime.datetime, datetime.datetime]]],
]:
    """
    Time-dependent A* with haversine heuristic (max speed 15 m/s ≈ 54 km/h).

    Returns identical output format to dijkstra_route so callers can swap
    implementations transparently.
    """
    depart_dt = _ensure_utc(depart_time_dt)
    start_ts = depart_dt.timestamp()

    def heuristic(u: int) -> float:
        if target not in graph.nodes or u not in graph.nodes:
            return 0.0
        n1 = graph.nodes[u]
        n2 = graph.nodes[target]
        return haversine_distance(n1["lat"], n1["lon"], n2["lat"], n2["lon"]) / A_STAR_MAX_SPEED_MS

    g_score: dict = {source: start_ts}
    came_from: dict = {}
    pq = [(start_ts + heuristic(source), start_ts, source)]

    while pq:
        _, curr_ts, u = heapq.heappop(pq)
        if u == target:
            break
        if curr_ts > g_score.get(u, 1e18):
            continue
        for v, eid in graph.neighbors(u):
            travel = graph.edge_travel_time(eid, curr_ts)
            arrival = curr_ts + travel
            if arrival < g_score.get(v, 1e18):
                g_score[v] = arrival
                came_from[v] = u
                heapq.heappush(pq, (arrival + heuristic(v), arrival, v))

    if target not in g_score:
        return None, None, None

    path = _reconstruct_path(came_from, source, target)
    per_seg = _build_segments(graph, path, start_ts)
    arrival_dt = datetime.datetime.fromtimestamp(g_score[target], tz=UTC)
    return arrival_dt, path, per_seg


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _reconstruct_path(prev: dict, source: int, target: int) -> List[int]:
    path = []
    node = target
    while node != source:
        path.append(node)
        node = prev[node]
    path.append(source)
    path.reverse()
    return path


def _build_segments(
    graph, path: List[int], start_ts: float
) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """Build per-segment UTC datetime tuples from a path."""
    per_seg = []
    t = start_ts
    for i in range(len(path) - 1):
        eid = graph.edge_id_between(path[i], path[i + 1])
        w = graph.edge_travel_time(eid, t)
        eta_start = datetime.datetime.fromtimestamp(t, tz=UTC)
        t += w
        eta_end = datetime.datetime.fromtimestamp(t, tz=UTC)
        per_seg.append((eta_start, eta_end))
    return per_seg
