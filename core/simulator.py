"""
Ambulance route simulator.

Simulates an ambulance travelling segment-by-segment along a route,
supports mid-journey traffic injection, and evaluates rerouting.

Usage (standalone):
    python -m core.simulator

Usage (as library):
    from core.simulator import SimulationEngine
    engine = SimulationEngine(graph)
    result = engine.run(ambulance_id, start_node, end_node, depart_dt)
"""

import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.config import REROUTE_THRESHOLD_SEC
from core.graph import EdgeUpdate, Graph
from core.routing import (
    _ensure_utc,
    _remaining_seconds,
    time_dependent_dijkstra,
)

UTC = datetime.timezone.utc
log = logging.getLogger("ambulance_routing.simulator")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SimEvent:
    sim_time: datetime.datetime
    kind: str  # DEPART | SEGMENT | TRAFFIC | REROUTE | ARRIVE
    message: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimResult:
    ambulance_id: str
    departed: datetime.datetime
    arrived: datetime.datetime
    total_seconds: float
    path: List[int]
    reroutes: int
    events: List[SimEvent]

    def log(self) -> str:
        lines = [f"=== Simulation: {self.ambulance_id} ==="]
        for ev in self.events:
            ts = ev.sim_time.strftime("%H:%M:%S")
            lines.append(f"  [{ts}] [{ev.kind:<8}] {ev.message}")
        total_min = int(self.total_seconds) // 60
        total_sec = int(self.total_seconds) % 60
        lines.append(f"  Total travel: {total_min}m {total_sec}s | Reroutes: {self.reroutes}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Traffic injection specification
# ---------------------------------------------------------------------------


@dataclass
class TrafficInjection:
    """Apply an edge update when the simulation clock reaches trigger_at."""

    trigger_at: datetime.datetime  # sim-clock UTC
    edge_updates: List[EdgeUpdate]
    label: str = ""


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------


class SimulationEngine:
    def __init__(self, graph: Graph, reroute_threshold_sec: float = REROUTE_THRESHOLD_SEC):
        self.graph = graph
        self.threshold = reroute_threshold_sec

    def run(
        self,
        ambulance_id: str,
        start_node: int,
        end_node: int,
        depart_dt: Optional[datetime.datetime] = None,
        traffic_injections: Optional[List[TrafficInjection]] = None,
        speed_multiplier: float = 1.0,  # >1 to run faster in wall-clock; sim is virtual time
    ) -> SimResult:
        """
        Run a complete simulation in virtual time (no real sleeping).

        The simulator advances virtual time segment-by-segment, checks for
        pending traffic injections, and evaluates rerouting after each injection.
        """
        depart_dt = _ensure_utc(depart_dt) if depart_dt else datetime.datetime.now(tz=UTC)
        injections = list(traffic_injections or [])
        events: List[SimEvent] = []
        reroute_count = 0

        # --- Initial route ---
        eta, path, per_seg = time_dependent_dijkstra(self.graph, start_node, end_node, depart_dt)
        if path is None:
            raise ValueError(f"No route from {start_node} to {end_node}")

        sim_time = depart_dt
        log.info(
            "Simulation started: ambulance_id=%s from=%d to=%d eta=%s",
            ambulance_id,
            start_node,
            end_node,
            eta.isoformat(),
        )
        events.append(
            SimEvent(
                sim_time,
                "DEPART",
                f"Ambulance {ambulance_id} departed node {start_node} -> destination {end_node}",
                {"path": path, "eta": eta.isoformat()},
            )
        )

        seg_index = 0

        while seg_index < len(per_seg):
            seg_start, seg_end = per_seg[seg_index]
            u = path[seg_index]
            v = path[seg_index + 1]
            seg_duration = (seg_end - seg_start).total_seconds()

            events.append(
                SimEvent(
                    sim_time,
                    "SEGMENT",
                    f"Travelling segment {seg_index+1}/{len(per_seg)}: "
                    f"node {u} -> node {v} ({int(seg_duration)}s)",
                    {"from": u, "to": v, "duration_sec": seg_duration},
                )
            )

            # Advance virtual time to end of this segment
            sim_time = seg_end

            # Apply any traffic injections that fire during this segment
            fired_injections = [inj for inj in injections if inj.trigger_at <= sim_time]
            for inj in fired_injections:
                injections.remove(inj)
                label = inj.label or f"{len(inj.edge_updates)} edge(s)"
                events.append(
                    SimEvent(
                        sim_time,
                        "TRAFFIC",
                        f"Traffic update applied: {label}",
                        {"updates": [u.model_dump() for u in inj.edge_updates]},
                    )
                )
                for eu in inj.edge_updates:
                    try:
                        self.graph.apply_edge_update(eu)
                    except Exception as e:
                        events.append(
                            SimEvent(
                                sim_time,
                                "TRAFFIC",
                                f"Edge update failed: {e}",
                            )
                        )

                # Evaluate reroute from current position
                current_node = v  # we just arrived at v
                remaining_path = path[seg_index + 1 :]
                if len(remaining_path) < 2:
                    continue  # at or near destination

                dest = path[-1]
                new_eta, new_path, new_per_seg = time_dependent_dijkstra(
                    self.graph, current_node, dest, sim_time
                )

                if new_path is None:
                    continue

                old_remaining = _remaining_seconds(eta, sim_time)
                new_remaining = _remaining_seconds(new_eta, sim_time)
                saved = old_remaining - new_remaining

                if saved >= self.threshold:
                    reroute_count += 1
                    events.append(
                        SimEvent(
                            sim_time,
                            "REROUTE",
                            f"Rerouted: save {int(saved)}s "
                            f"({int(old_remaining)}s -> {int(new_remaining)}s remaining)",
                            {
                                "old_path": path[seg_index + 1 :],
                                "new_path": new_path,
                                "time_saved_sec": saved,
                            },
                        )
                    )
                    # Update route state
                    path = path[: seg_index + 1] + new_path
                    per_seg = per_seg[: seg_index + 1] + new_per_seg
                    eta = new_eta
                else:
                    events.append(
                        SimEvent(
                            sim_time,
                            "REROUTE",
                            f"Reroute not beneficial (would save {int(saved)}s < {int(self.threshold)}s threshold)",
                        )
                    )

            seg_index += 1

        total_s = (sim_time - depart_dt).total_seconds()
        log.info(
            "Simulation completed: ambulance_id=%s total=%.0fs reroutes=%d",
            ambulance_id,
            total_s,
            reroute_count,
        )
        events.append(
            SimEvent(
                sim_time,
                "ARRIVE",
                f"Ambulance {ambulance_id} arrived at node {path[-1]}",
                {"total_seconds": total_s},
            )
        )

        return SimResult(
            ambulance_id=ambulance_id,
            departed=depart_dt,
            arrived=sim_time,
            total_seconds=(sim_time - depart_dt).total_seconds(),
            path=path,
            reroutes=reroute_count,
            events=events,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _demo():
    import logging as _logging
    import os

    from core.logging_config import configure_logging

    configure_logging()
    _log = _logging.getLogger("ambulance_routing.demo")

    graph_path = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_graph.json")
    g = Graph()
    g.load_from_file(graph_path)

    depart = datetime.datetime(2026, 6, 12, 8, 0, 0, tzinfo=UTC)
    inject_time = depart + datetime.timedelta(seconds=40)
    injections = [
        TrafficInjection(
            trigger_at=inject_time,
            edge_updates=[EdgeUpdate(edge_id=2, multiplier=3.0)],
            label="Heavy congestion on edge 2",
        )
    ]

    engine = SimulationEngine(g)
    result = engine.run(
        "AMB-001", start_node=1, end_node=3, depart_dt=depart, traffic_injections=injections
    )
    _log.info("Simulation complete\n%s", result.log())


if __name__ == "__main__":
    _demo()
