import json
from typing import Tuple, List, Dict, Optional
import math
from pydantic import BaseModel

class EdgeUpdate(BaseModel):
    edge_id: int
    multiplier: Optional[float] = None
    absolute_time: Optional[float] = None

class Graph:
    def __init__(self):
        # simple adjacency: {u: [(v, edge_id), ...], ...}
        self.adj = {}
        self.edges = {}   # edge_id -> {u, v, base_time, distance, time_buckets(optional)}
        self.nodes = {}   # node_id -> {"lat":..,"lon":..}
        self._next_edge_id = 1

    def add_node(self, node_id: int, lat: float, lon: float):
        self.nodes[node_id] = {"lat": lat, "lon": lon}
        self.adj.setdefault(node_id, [])

    def add_edge(self, u: int, v: int, base_time: float, distance: float, time_buckets: List[dict]=None, is_emergency_allowed: bool=True):
        eid = self._next_edge_id
        self._next_edge_id += 1
        self.adj.setdefault(u, []).append((v, eid))
        self.edges[eid] = {
            "u": u, "v": v, "base_time": base_time, "distance": distance,
            "time_buckets": time_buckets or [], "is_emergency_allowed": is_emergency_allowed,
            "multiplier": 1.0
        }
        return eid

    def load_from_file(self, path: str):
        with open(path, "r") as f:
            j = json.load(f)
        for n in j.get("nodes", []):
            self.add_node(n["id"], n["lat"], n["lon"])
        for e in j.get("edges", []):
            self.add_edge(e["from"], e["to"], e["base_time"], e.get("distance",0), e.get("time_buckets"))

    def nearest_node(self, latlon: Tuple[float,float]) -> int:
        # brute force — fine for MVP
        lat, lon = latlon
        best, bd = None, float('inf')
        for nid, nd in self.nodes.items():
            d = (nd['lat'] - lat)**2 + (nd['lon'] - lon)**2
            if d < bd:
                bd = d; best = nid
        return best

    def edge_travel_time(self, edge_id: int, depart_time_seconds: float) -> float:
        e = self.edges[edge_id]
        # if time_buckets exist, choose a bucket by seconds%86400
        if e["time_buckets"]:
            t = depart_time_seconds % 86400
            for b in e["time_buckets"]:
                if b["start"] <= t < b["end"]:
                    return b["avg_time"] * e.get("multiplier", 1.0)
        return e["base_time"] * e.get("multiplier", 1.0)

    def neighbors(self, u: int):
        return self.adj.get(u, [])

    def edge_id_between(self, u: int, v: int):
        for x, eid in self.adj.get(u, []):
            if x == v:
                return eid
        return None

    def apply_edge_update(self, edge_update: EdgeUpdate):
        edge_id = edge_update.edge_id
        if edge_id not in self.edges:
            return
        if edge_update.multiplier is not None:
            self.edges[edge_id]['multiplier'] *= edge_update.multiplier
        if edge_update.absolute_time is not None:
            self.edges[edge_id]['absolute_time'] = edge_update.absolute_time
