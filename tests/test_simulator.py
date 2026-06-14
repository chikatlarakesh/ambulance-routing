"""Tests for core/simulator.py"""

import datetime

import pytest

from core.graph import EdgeUpdate, Graph
from core.simulator import SimulationEngine, TrafficInjection

UTC = datetime.timezone.utc


def make_graph() -> Graph:
    g = Graph()
    for nid, lat, lon in [(1, 0.0, 0.0), (2, 0.0, 0.5), (3, 0.0, 1.0)]:
        g.add_node(nid, lat, lon)
    g.add_edge(1, 2, 60, 500)
    g.add_edge(2, 3, 60, 500)
    return g


def utc_dt(**kw):
    defaults = dict(year=2026, month=6, day=12, hour=8, minute=0, second=0)
    defaults.update(kw)
    return datetime.datetime(**defaults, tzinfo=UTC)


class TestSimulationEngine:
    def test_basic_run_completes(self):
        g = make_graph()
        engine = SimulationEngine(g)
        result = engine.run("AMB-01", 1, 3, depart_dt=utc_dt())
        assert result.ambulance_id == "AMB-01"
        assert result.path[0] == 1
        assert result.path[-1] == 3

    def test_total_seconds_correct(self):
        g = make_graph()
        engine = SimulationEngine(g)
        result = engine.run("AMB-01", 1, 3, depart_dt=utc_dt())
        assert result.total_seconds == 120.0

    def test_events_include_depart_and_arrive(self):
        g = make_graph()
        engine = SimulationEngine(g)
        result = engine.run("AMB-01", 1, 3, depart_dt=utc_dt())
        kinds = [e.kind for e in result.events]
        assert "DEPART" in kinds
        assert "ARRIVE" in kinds

    def test_traffic_injection_fires(self):
        g = make_graph()
        inject_time = utc_dt(second=30)  # fires after first segment starts
        injections = [
            TrafficInjection(
                trigger_at=inject_time,
                edge_updates=[EdgeUpdate(edge_id=2, multiplier=1.5)],
                label="Test traffic",
            )
        ]
        engine = SimulationEngine(g)
        result = engine.run("AMB-01", 1, 3, depart_dt=utc_dt(), traffic_injections=injections)
        kinds = [e.kind for e in result.events]
        assert "TRAFFIC" in kinds

    def test_reroute_triggered_when_bypass_opens(self):
        """
        Reroute is beneficial when a fast bypass was initially blocked (high
        multiplier) so Dijkstra chose the longer direct route, then traffic
        clears the bypass making it much faster than the stored ETA's remaining
        path.

        Initial state:
          1->2 (60s), 2->3 (300s, direct), 2->4 (10s×50=500s), 4->3 (10s×50=500s)
          Dijkstra picks [1,2,3] = 360s  (bypass is 1060s)

        After seg-1 traffic event (reset bypass multipliers to 1.0):
          old_remaining = 360-60 = 300s
          new_remaining from node 2 = 2->4->3 = 10+10 = 20s
          saved = 280s > 120s threshold  → REROUTE
        """
        import datetime as _dt

        g = Graph()
        for nid, lat, lon in [(1, 0.0, 0.0), (2, 0.0, 0.5), (3, 0.0, 1.0), (4, 0.0, 0.6)]:
            g.add_node(nid, lat, lon)
        g.add_edge(1, 2, 60, 500)  # edge 1
        g.add_edge(2, 3, 300, 2000)  # edge 2 – slow direct route
        g.add_edge(2, 4, 10, 100)  # edge 3 – bypass leg A
        g.add_edge(4, 3, 10, 100)  # edge 4 – bypass leg B

        # Block the bypass so Dijkstra takes the direct route initially
        g.apply_edge_update(EdgeUpdate(edge_id=3, multiplier=50.0))
        g.apply_edge_update(EdgeUpdate(edge_id=4, multiplier=50.0))

        depart = utc_dt()
        # Traffic event fires 30s in (before seg-1 ends at 60s) → picked up after seg-1
        inject_time = depart + _dt.timedelta(seconds=30)
        injections = [
            TrafficInjection(
                trigger_at=inject_time,
                edge_updates=[
                    EdgeUpdate(edge_id=3, multiplier=1.0),
                    EdgeUpdate(edge_id=4, multiplier=1.0),
                ],
                label="Bypass road opened",
            )
        ]
        engine = SimulationEngine(g, reroute_threshold_sec=120)
        result = engine.run("AMB-01", 1, 3, depart_dt=depart, traffic_injections=injections)
        kinds = [e.kind for e in result.events]
        assert "REROUTE" in kinds
        assert result.reroutes > 0

    def test_no_route_raises(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        # no edges
        engine = SimulationEngine(g)
        with pytest.raises(ValueError):
            engine.run("AMB-01", 1, 2, depart_dt=utc_dt())

    def test_log_output_is_string(self):
        g = make_graph()
        engine = SimulationEngine(g)
        result = engine.run("AMB-01", 1, 3, depart_dt=utc_dt())
        log = result.log()
        assert isinstance(log, str)
        assert "AMB-01" in log
