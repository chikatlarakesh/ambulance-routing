"""Tests for core/routing.py"""

import datetime

from core.graph import EdgeUpdate, Graph
from core.routing import (
    _ensure_utc,
    _remaining_seconds,
    a_star_route,
    dijkstra_route,
    haversine_distance,
    time_dependent_dijkstra,
)

UTC = datetime.timezone.utc


def make_linear_graph() -> Graph:
    """1 -> 2 -> 3, each edge 60s."""
    g = Graph()
    g.add_node(1, 0.0, 0.0)
    g.add_node(2, 0.0, 1.0)
    g.add_node(3, 1.0, 1.0)
    g.add_edge(1, 2, 60, 100)
    g.add_edge(2, 3, 60, 100)
    return g


def make_diamond_graph() -> Graph:
    """
    1 --60s--> 2 --60s--> 4
    1 --200s-> 3 --60s--> 4
    """
    g = Graph()
    for nid, lat, lon in [(1, 0.0, 0.0), (2, 0.0, 0.5), (3, 0.0, -0.5), (4, 0.0, 1.0)]:
        g.add_node(nid, lat, lon)
    g.add_edge(1, 2, 60, 500)
    g.add_edge(2, 4, 60, 500)
    g.add_edge(1, 3, 200, 2000)
    g.add_edge(3, 4, 60, 500)
    return g


def utc_dt(year=2026, month=6, day=12, hour=8, minute=0, second=0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, second, tzinfo=UTC)


# ------------------------------------------------------------------
# _ensure_utc
# ------------------------------------------------------------------


class TestEnsureUtc:
    def test_naive_datetime_gets_utc(self):
        dt = datetime.datetime(2026, 1, 1, 12, 0, 0)
        result = _ensure_utc(dt)
        assert result.tzinfo == UTC

    def test_aware_datetime_converted(self):
        import pytz

        ist = pytz.timezone("Asia/Kolkata")
        dt = ist.localize(datetime.datetime(2026, 1, 1, 17, 30, 0))
        result = _ensure_utc(dt)
        assert result.hour == 12
        assert result.tzinfo == UTC

    def test_epoch_float(self):
        ts = 1749600000.0  # some epoch
        result = _ensure_utc(ts)
        assert isinstance(result, datetime.datetime)
        assert result.tzinfo == UTC

    def test_iso_string_with_z(self):
        result = _ensure_utc("2026-06-12T08:00:00Z")
        assert result == utc_dt()

    def test_iso_string_without_tz_assumes_utc(self):
        result = _ensure_utc("2026-06-12T08:00:00")
        assert result == utc_dt()


# ------------------------------------------------------------------
# _remaining_seconds
# ------------------------------------------------------------------


class TestRemainingSeconds:
    def test_positive_remaining(self):
        eta = utc_dt(hour=9)
        now = utc_dt(hour=8)
        assert _remaining_seconds(eta, now) == 3600.0

    def test_past_eta_returns_zero(self):
        eta = utc_dt(hour=7)
        now = utc_dt(hour=8)
        assert _remaining_seconds(eta, now) == 0.0

    def test_same_time_returns_zero(self):
        t = utc_dt()
        assert _remaining_seconds(t, t) == 0.0


# ------------------------------------------------------------------
# haversine_distance
# ------------------------------------------------------------------


class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_distance(12.97, 77.59, 12.97, 77.59) == 0.0

    def test_known_distance(self):
        # Bangalore Central to roughly 1km away
        d = haversine_distance(12.97, 77.59, 12.979, 77.59)
        assert 900 < d < 1100


# ------------------------------------------------------------------
# Dijkstra
# ------------------------------------------------------------------


class TestDijkstraRoute:
    def test_linear_path(self):
        g = make_linear_graph()
        arrival, path, segs = dijkstra_route(g, 1, 3, utc_dt())
        assert path == [1, 2, 3]

    def test_arrival_is_utc_aware(self):
        g = make_linear_graph()
        arrival, path, segs = dijkstra_route(g, 1, 3, utc_dt())
        assert arrival.tzinfo is not None

    def test_total_time_correct(self):
        g = make_linear_graph()
        depart = utc_dt()
        arrival, path, segs = dijkstra_route(g, 1, 3, depart)
        assert int((arrival - depart).total_seconds()) == 120

    def test_per_segment_times_utc_aware(self):
        g = make_linear_graph()
        _, _, segs = dijkstra_route(g, 1, 3, utc_dt())
        for s, e in segs:
            assert s.tzinfo is not None
            assert e.tzinfo is not None

    def test_chooses_shorter_path_in_diamond(self):
        g = make_diamond_graph()
        arrival, path, segs = dijkstra_route(g, 1, 4, utc_dt())
        assert path == [1, 2, 4]

    def test_no_route_returns_none_triple(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        # no edge
        arrival, path, segs = dijkstra_route(g, 1, 2, utc_dt())
        assert arrival is None and path is None and segs is None

    def test_source_equals_target(self):
        g = make_linear_graph()
        arrival, path, segs = dijkstra_route(g, 1, 1, utc_dt())
        assert path == [1]
        assert segs == []

    def test_multiplier_increases_cost(self):
        g = make_linear_graph()
        eid = g.edge_id_between(1, 2)
        g.apply_edge_update(EdgeUpdate(edge_id=eid, multiplier=10.0))
        depart = utc_dt()
        arrival, path, segs = dijkstra_route(g, 1, 3, depart)
        total = (arrival - depart).total_seconds()
        # 10*60 + 60 = 660
        assert total == 660.0

    def test_time_dependent_uses_departure_time(self):
        """With a time bucket active at 8am, cost should differ from midnight."""
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        # Time bucket 08:00-11:00 → 300s
        buckets = [{"start": 28800, "end": 39600, "avg_time": 300}]
        g.add_edge(1, 2, 60, 100, time_buckets=buckets)

        # 8am — should use bucket (300s)
        t8am = utc_dt(hour=8)
        arr_8, _, _ = dijkstra_route(g, 1, 2, t8am)
        total_8 = (arr_8 - t8am).total_seconds()
        assert total_8 == 300.0

        # midnight — should use base (60s)
        t_midnight = utc_dt(hour=0)
        arr_mid, _, _ = dijkstra_route(g, 1, 2, t_midnight)
        total_mid = (arr_mid - t_midnight).total_seconds()
        assert total_mid == 60.0

    def test_absolute_override_takes_priority(self):
        g = make_linear_graph()
        eid = g.edge_id_between(1, 2)
        g.apply_edge_update(EdgeUpdate(edge_id=eid, absolute_time=999.0, multiplier=0.001))
        depart = utc_dt()
        arrival, _, _ = dijkstra_route(g, 1, 2, depart)
        assert int((arrival - depart).total_seconds()) == 999


# ------------------------------------------------------------------
# time_dependent_dijkstra (alias check)
# ------------------------------------------------------------------


class TestTimeDependentDijkstra:
    def test_produces_same_result_as_dijkstra(self):
        g = make_diamond_graph()
        t = utc_dt()
        arr1, p1, s1 = dijkstra_route(g, 1, 4, t)
        arr2, p2, s2 = time_dependent_dijkstra(g, 1, 4, t)
        assert p1 == p2
        assert arr1 == arr2


# ------------------------------------------------------------------
# A*
# ------------------------------------------------------------------


class TestAStarRoute:
    def test_linear_path(self):
        g = make_linear_graph()
        arrival, path, segs = a_star_route(g, 1, 3, utc_dt())
        assert path == [1, 2, 3]

    def test_matches_dijkstra_eta(self):
        g = make_diamond_graph()
        t = utc_dt()
        arr_d, path_d, _ = dijkstra_route(g, 1, 4, t)
        arr_a, path_a, _ = a_star_route(g, 1, 4, t)
        assert arr_d == arr_a

    def test_arrival_is_utc_aware(self):
        g = make_linear_graph()
        arrival, _, _ = a_star_route(g, 1, 3, utc_dt())
        assert arrival.tzinfo is not None

    def test_per_segment_times_utc_aware(self):
        g = make_linear_graph()
        _, _, segs = a_star_route(g, 1, 3, utc_dt())
        for s, e in segs:
            assert s.tzinfo is not None
            assert e.tzinfo is not None

    def test_no_route_returns_none_triple(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        arrival, path, segs = a_star_route(g, 1, 2, utc_dt())
        assert arrival is None and path is None and segs is None

    def test_source_equals_target(self):
        g = make_linear_graph()
        arrival, path, segs = a_star_route(g, 1, 1, utc_dt())
        assert path == [1]
        assert segs == []
