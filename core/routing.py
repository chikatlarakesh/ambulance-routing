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

def a_star_route(graph, start_node, end_node):
    """
    Returns path, per_segment_times
    """
    import heapq

    open_set = []
    heapq.heappush(open_set, (0, start_node))
    came_from = {}
    g_score = {start_node: 0}

    # Precompute end node lat/lon
    end_lat = graph.nodes[end_node]['lat']
    end_lon = graph.nodes[end_node]['lon']

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == end_node:
            # reconstruct path
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path, None  # placeholder for per_segment_times

        for neighbor in graph.neighbors(current):
            tentative_g = g_score[current] + graph.edge_weight(current, neighbor)
            if neighbor not in g_score or tentative_g < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g

                # Heuristic: Haversine
                lat = graph.nodes[neighbor]['lat']
                lon = graph.nodes[neighbor]['lon']
                h = haversine_distance(lat, lon, end_lat, end_lon)

                heapq.heappush(open_set, (tentative_g + h, neighbor))

    return None, None  # no path found

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
