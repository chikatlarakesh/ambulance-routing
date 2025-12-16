import heapq
from typing import Tuple, List, Optional
import datetime
import time
import math

def haversine_distance(lat1, lon1, lat2, lon2):
    # Earth radius in meters
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def a_star_route(graph, source: int, target: int, depart_time_dt: datetime.datetime):
    """
    Time-dependent A* routing using travel time + haversine heuristic.
    Returns (arrival_time, path, per_segment_times)
    """

    pq = []
    start_ts = depart_time_dt.timestamp()

    # g_score = earliest arrival timestamp at node
    g_score = {source: start_ts}
    came_from = {}

    # heuristic scaling: assume max speed ≈ 15 m/s (~54 km/h)
    MAX_SPEED = 15.0

    def heuristic(u):
        lat1, lon1 = graph.nodes[u]["lat"], graph.nodes[u]["lon"]
        lat2, lon2 = graph.nodes[target]["lat"], graph.nodes[target]["lon"]
        dist = haversine_distance(lat1, lon1, lat2, lon2)
        return dist / MAX_SPEED

    # (f_score, arrival_time, node)
    heapq.heappush(pq, (heuristic(source), start_ts, source))

    while pq:
        _, curr_time, u = heapq.heappop(pq)
        print("Visiting node:", u)
        if u == target:
            break

        if curr_time > g_score.get(u, float("inf")):
            continue

        for v, eid in graph.neighbors(u):
        

            travel_time = graph.edge_travel_time(eid, curr_time)
            arrival = curr_time + travel_time

            if arrival < g_score.get(v, float("inf")):
                g_score[v] = arrival
                came_from[v] = u
                f_score = arrival + heuristic(v)
                heapq.heappush(pq, (f_score, arrival, v))

    if target not in g_score:
        return None, None, None

    # ---- Reconstruct path ----
    path = []
    node = target
    while node != source:
        path.append(node)
        node = came_from[node]
    path.append(source)
    path.reverse()

    # ---- Build per-segment times ----
    per_segment_times = []
    t = start_ts
    for i in range(len(path) - 1):
        eid = graph.edge_id_between(path[i], path[i + 1])
        w = graph.edge_travel_time(eid, t)
        eta_start = datetime.datetime.fromtimestamp(t)
        t += w
        eta_end = datetime.datetime.fromtimestamp(t)
        per_segment_times.append((eta_start, eta_end))

    arrival_dt = datetime.datetime.fromtimestamp(g_score[target])

    return arrival_dt, path, per_segment_times


# Static Dijkstra (returns arrival_time, path)
def dijkstra_route(graph, source: int, target: int, depart_time_dt: datetime.datetime):
    # simple static weights (base_time * multiplier)
    pq = []
    dist = {}
    prev = {}
    start = depart_time_dt.timestamp()
    dist[source] = start
    heapq.heappush(pq, (start, source))
    while pq:
        curr_time, u = heapq.heappop(pq)
        if u == target:
            break
        if curr_time > dist.get(u, 1e99):
            continue
        for v, eid in graph.neighbors(u):
            w = graph.edge_travel_time(eid, curr_time)  # uses multiplier
            arrival = curr_time + w
            if arrival < dist.get(v, 1e99):
                dist[v] = arrival
                prev[v] = u
                heapq.heappush(pq, (arrival, v))
    if target not in dist:
        return None, None, None
    # reconstruct path
    path = []
    node = target
    while node != source:
        path.append(node)
        node = prev[node]
    path.append(source)
    path.reverse()
    arrival_dt = datetime.datetime.fromtimestamp(dist[target])
    # per-segment times
    per_seg = []
    t = start
    for i in range(len(path)-1):
        eid = graph.edge_id_between(path[i], path[i+1])
        w = graph.edge_travel_time(eid, t)
        eta_start = datetime.datetime.fromtimestamp(t)
        t = t + w
        eta_end = datetime.datetime.fromtimestamp(t)
        per_seg.append((eta_start, eta_end))
    return arrival_dt, path, per_seg

# Time-dependent Dijkstra (label-setting)
def time_dependent_dijkstra(graph, source: int, target: int, depart_time_dt: datetime.datetime):
    # This implementation is same as the (label-setting) Dijkstra using edge travel_time(depart_time)
    # For complex piecewise travel_time functions, ensure FIFO property. MVP: ok.
    return dijkstra_route(graph, source, target, depart_time_dt)

