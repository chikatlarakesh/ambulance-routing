import json
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel


class EdgeUpdate(BaseModel):
    edge_id: int
    multiplier: Optional[float] = None
    absolute_time: Optional[float] = None  # seconds; overrides all other costs


class NodeNotFoundError(Exception):
    pass


class EdgeNotFoundError(Exception):
    pass


class InvalidGraphError(Exception):
    pass


class Graph:
    def __init__(self):
        self.adj: Dict[int, List[Tuple[int, int]]] = {}
        self.edges: Dict[int, Dict[str, Any]] = {}
        self.nodes: Dict[int, Dict[str, Any]] = {}
        self._next_edge_id = 1

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_node(self, node_id: int, lat: float, lon: float, name: str = "") -> None:
        self.nodes[node_id] = {"lat": lat, "lon": lon, "name": name or str(node_id)}
        self.adj.setdefault(node_id, [])

    def add_edge(
        self,
        u: int,
        v: int,
        base_time: float,
        distance: float,
        time_buckets: Optional[List[dict]] = None,
        is_emergency_allowed: bool = True,
        edge_id: Optional[int] = None,
    ) -> int:
        if u not in self.nodes:
            raise InvalidGraphError(f"Source node {u} not found")
        if v not in self.nodes:
            raise InvalidGraphError(f"Destination node {v} not found")
        if base_time < 0:
            raise InvalidGraphError(f"Edge {u}->{v}: base_time cannot be negative")
        if distance < 0:
            raise InvalidGraphError(f"Edge {u}->{v}: distance cannot be negative")

        eid = edge_id if edge_id is not None else self._next_edge_id
        if eid in self.edges:
            raise InvalidGraphError(f"Duplicate edge_id {eid}")
        if eid >= self._next_edge_id:
            self._next_edge_id = eid + 1

        self.adj.setdefault(u, []).append((v, eid))
        self.edges[eid] = {
            "u": u,
            "v": v,
            "base_time": base_time,
            "distance": distance,
            "time_buckets": time_buckets or [],
            "is_emergency_allowed": is_emergency_allowed,
            "multiplier": 1.0,
            "absolute_time": None,
        }
        return eid

    def load_from_file(self, path: str) -> None:
        with open(path, "r") as f:
            j = json.load(f)
        for n in j.get("nodes", []):
            self.add_node(n["id"], n["lat"], n["lon"], n.get("name", ""))
        for e in j.get("edges", []):
            explicit_id = e.get("edge_id")
            self.add_edge(
                e["from"],
                e["to"],
                e["base_time"],
                e.get("distance", 0),
                e.get("time_buckets"),
                e.get("is_emergency_allowed", True),
                edge_id=explicit_id,
            )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def nearest_node(self, latlon: Tuple[float, float]) -> int:
        lat, lon = latlon
        best, bd = None, float("inf")
        for nid, nd in self.nodes.items():
            d = (nd["lat"] - lat) ** 2 + (nd["lon"] - lon) ** 2
            if d < bd:
                bd, best = d, nid
        if best is None:
            raise NodeNotFoundError("Graph has no nodes")
        return best

    def edge_travel_time(self, edge_id: int, depart_time_seconds: float) -> float:
        """
        Return travel time in seconds for an edge at a given departure epoch.

        Priority order:
          1. absolute_time override (set via traffic snapshot)
          2. matching time_bucket  (uses bucket avg_time * multiplier)
          3. base_time * multiplier
        """
        if edge_id not in self.edges:
            raise EdgeNotFoundError(f"Edge {edge_id} not found")
        e = self.edges[edge_id]

        if e.get("absolute_time") is not None:
            return float(e["absolute_time"])

        if e["time_buckets"]:
            t = depart_time_seconds % 86400
            for b in e["time_buckets"]:
                if b["start"] <= t < b["end"]:
                    return b["avg_time"] * e.get("multiplier", 1.0)

        return e["base_time"] * e.get("multiplier", 1.0)

    def neighbors(self, u: int) -> List[Tuple[int, int]]:
        return self.adj.get(u, [])

    def edge_id_between(self, u: int, v: int) -> Optional[int]:
        for x, eid in self.adj.get(u, []):
            if x == v:
                return eid
        return None

    # ------------------------------------------------------------------
    # Traffic updates
    # ------------------------------------------------------------------

    def apply_edge_update(self, edge_update: "EdgeUpdate") -> None:
        edge_id = edge_update.edge_id
        if edge_id not in self.edges:
            raise EdgeNotFoundError(f"Edge {edge_id} not found")
        if edge_update.multiplier is not None:
            # Replace, not accumulate
            self.edges[edge_id]["multiplier"] = edge_update.multiplier
        if edge_update.absolute_time is not None:
            self.edges[edge_id]["absolute_time"] = edge_update.absolute_time

    def reset_edge_overrides(self, edge_id: Optional[int] = None) -> None:
        """Reset absolute_time and multiplier. If edge_id is None, reset all edges."""
        targets = [edge_id] if edge_id is not None else list(self.edges.keys())
        for eid in targets:
            if eid in self.edges:
                self.edges[eid]["absolute_time"] = None
                self.edges[eid]["multiplier"] = 1.0

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    def graph_to_dict(self) -> dict:
        return {
            "nodes": [{"id": nid, **nd} for nid, nd in self.nodes.items()],
            "edges": [
                {
                    "edge_id": eid,
                    "u": e["u"],
                    "v": e["v"],
                    "base_time": e["base_time"],
                    "distance": e["distance"],
                    "multiplier": e["multiplier"],
                    "absolute_time": e["absolute_time"],
                    "time_buckets": e["time_buckets"],
                    "is_emergency_allowed": e["is_emergency_allowed"],
                }
                for eid, e in self.edges.items()
            ],
        }
