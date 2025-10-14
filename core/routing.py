import heapq
from typing import Tuple, List, Optional
import datetime
import time

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

# Placeholder A* (you can replace with heuristic improved version)
def a_star_route(graph, source: int, target: int, depart_time_dt):
    # For MVP, we call dijkstra
    return dijkstra_route(graph, source, target, depart_time_dt)
