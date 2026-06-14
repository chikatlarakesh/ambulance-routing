"""Tests for core/graph.py"""

import pytest

from core.graph import EdgeNotFoundError, EdgeUpdate, Graph, InvalidGraphError, NodeNotFoundError


def simple_graph() -> Graph:
    g = Graph()
    g.add_node(1, 0.0, 0.0, "A")
    g.add_node(2, 0.0, 1.0, "B")
    g.add_node(3, 1.0, 1.0, "C")
    g.add_edge(1, 2, 60, 1000)
    g.add_edge(2, 3, 60, 1000)
    g.add_edge(1, 3, 200, 3000)
    return g


# ------------------------------------------------------------------
# Node creation
# ------------------------------------------------------------------


class TestNodeCreation:
    def test_add_node_stores_lat_lon(self):
        g = Graph()
        g.add_node(1, 12.97, 77.59, "Test")
        assert g.nodes[1]["lat"] == 12.97
        assert g.nodes[1]["lon"] == 77.59
        assert g.nodes[1]["name"] == "Test"

    def test_add_node_creates_empty_adjacency(self):
        g = Graph()
        g.add_node(5, 0.0, 0.0)
        assert g.adj[5] == []

    def test_add_node_default_name_is_str_id(self):
        g = Graph()
        g.add_node(7, 0.0, 0.0)
        assert g.nodes[7]["name"] == "7"


# ------------------------------------------------------------------
# Edge creation
# ------------------------------------------------------------------


class TestEdgeCreation:
    def test_add_edge_stores_data(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        eid = g.add_edge(1, 2, 45.0, 800.0)
        e = g.edges[eid]
        assert e["base_time"] == 45.0
        assert e["distance"] == 800.0
        assert e["u"] == 1
        assert e["v"] == 2
        assert e["multiplier"] == 1.0
        assert e["absolute_time"] is None

    def test_add_edge_updates_adjacency(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        eid = g.add_edge(1, 2, 10, 100)
        assert (2, eid) in g.adj[1]

    def test_add_edge_explicit_id(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        eid = g.add_edge(1, 2, 10, 100, edge_id=42)
        assert eid == 42
        assert 42 in g.edges

    def test_add_edge_rejects_missing_source_node(self):
        g = Graph()
        g.add_node(2, 0, 0)
        with pytest.raises(InvalidGraphError):
            g.add_edge(99, 2, 10, 100)

    def test_add_edge_rejects_missing_dest_node(self):
        g = Graph()
        g.add_node(1, 0, 0)
        with pytest.raises(InvalidGraphError):
            g.add_edge(1, 99, 10, 100)

    def test_add_edge_rejects_negative_base_time(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        with pytest.raises(InvalidGraphError):
            g.add_edge(1, 2, -1, 100)

    def test_add_edge_rejects_negative_distance(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        with pytest.raises(InvalidGraphError):
            g.add_edge(1, 2, 10, -1)

    def test_add_edge_rejects_duplicate_id(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        g.add_edge(1, 2, 10, 100, edge_id=5)
        with pytest.raises(InvalidGraphError):
            g.add_edge(1, 2, 20, 200, edge_id=5)


# ------------------------------------------------------------------
# Nearest node
# ------------------------------------------------------------------


class TestNearestNode:
    def test_returns_exact_match(self):
        g = simple_graph()
        assert g.nearest_node((0.0, 0.0)) == 1

    def test_returns_closest(self):
        g = simple_graph()
        # (0.01, 0.99) is closest to node 2 (0, 1)
        assert g.nearest_node((0.01, 0.99)) == 2

    def test_empty_graph_raises(self):
        g = Graph()
        with pytest.raises(NodeNotFoundError):
            g.nearest_node((0, 0))


# ------------------------------------------------------------------
# Edge travel time
# ------------------------------------------------------------------


class TestEdgeTravelTime:
    def test_base_case(self):
        g = simple_graph()
        eid = g.edge_id_between(1, 2)
        assert g.edge_travel_time(eid, 0.0) == 60.0

    def test_multiplier_applied(self):
        g = simple_graph()
        eid = g.edge_id_between(1, 2)
        g.edges[eid]["multiplier"] = 2.0
        assert g.edge_travel_time(eid, 0.0) == 120.0

    def test_absolute_time_overrides_multiplier(self):
        g = simple_graph()
        eid = g.edge_id_between(1, 2)
        g.edges[eid]["absolute_time"] = 999.0
        g.edges[eid]["multiplier"] = 100.0
        assert g.edge_travel_time(eid, 0.0) == 999.0

    def test_time_bucket_used(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        buckets = [{"start": 28800, "end": 39600, "avg_time": 180}]  # 08:00-11:00
        g.add_edge(1, 2, 60, 1000, time_buckets=buckets)
        eid = g.edge_id_between(1, 2)
        # 9am = 32400 seconds in day
        assert g.edge_travel_time(eid, 32400.0) == 180.0

    def test_time_bucket_multiplier_applied(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        buckets = [{"start": 28800, "end": 39600, "avg_time": 100}]
        g.add_edge(1, 2, 60, 1000, time_buckets=buckets)
        eid = g.edge_id_between(1, 2)
        g.edges[eid]["multiplier"] = 1.5
        assert g.edge_travel_time(eid, 32400.0) == 150.0

    def test_bucket_fallback_when_outside_range(self):
        g = Graph()
        g.add_node(1, 0, 0)
        g.add_node(2, 0, 1)
        buckets = [{"start": 28800, "end": 39600, "avg_time": 180}]
        g.add_edge(1, 2, 60, 1000, time_buckets=buckets)
        eid = g.edge_id_between(1, 2)
        # Midnight = 0 seconds — not in bucket
        assert g.edge_travel_time(eid, 0.0) == 60.0

    def test_invalid_edge_raises(self):
        g = Graph()
        with pytest.raises(EdgeNotFoundError):
            g.edge_travel_time(999, 0.0)


# ------------------------------------------------------------------
# Apply edge update
# ------------------------------------------------------------------


class TestApplyEdgeUpdate:
    def test_multiplier_replaces_not_accumulates(self):
        g = simple_graph()
        eid = g.edge_id_between(1, 2)
        g.apply_edge_update(EdgeUpdate(edge_id=eid, multiplier=1.5))
        g.apply_edge_update(EdgeUpdate(edge_id=eid, multiplier=1.5))
        # Should be 1.5, not 2.25
        assert g.edges[eid]["multiplier"] == 1.5

    def test_absolute_time_stored(self):
        g = simple_graph()
        eid = g.edge_id_between(1, 2)
        g.apply_edge_update(EdgeUpdate(edge_id=eid, absolute_time=300.0))
        assert g.edges[eid]["absolute_time"] == 300.0

    def test_invalid_edge_raises(self):
        g = simple_graph()
        with pytest.raises(EdgeNotFoundError):
            g.apply_edge_update(EdgeUpdate(edge_id=999, multiplier=2.0))

    def test_reset_edge_overrides(self):
        g = simple_graph()
        eid = g.edge_id_between(1, 2)
        g.apply_edge_update(EdgeUpdate(edge_id=eid, multiplier=3.0, absolute_time=500.0))
        g.reset_edge_overrides(eid)
        assert g.edges[eid]["multiplier"] == 1.0
        assert g.edges[eid]["absolute_time"] is None

    def test_reset_all_overrides(self):
        g = simple_graph()
        for eid in g.edges:
            g.apply_edge_update(EdgeUpdate(edge_id=eid, multiplier=2.0))
        g.reset_edge_overrides()
        for eid in g.edges:
            assert g.edges[eid]["multiplier"] == 1.0


# ------------------------------------------------------------------
# Load from file
# ------------------------------------------------------------------


class TestLoadFromFile:
    def test_load_sample_graph(self, tmp_path):
        import json

        data = {
            "nodes": [
                {"id": 1, "lat": 10.0, "lon": 20.0, "name": "Start"},
                {"id": 2, "lat": 10.1, "lon": 20.1, "name": "End"},
            ],
            "edges": [
                {"edge_id": 7, "from": 1, "to": 2, "base_time": 30, "distance": 500},
            ],
        }
        p = tmp_path / "graph.json"
        p.write_text(json.dumps(data))
        g = Graph()
        g.load_from_file(str(p))
        assert 1 in g.nodes
        assert 2 in g.nodes
        assert 7 in g.edges
        assert g.nodes[1]["name"] == "Start"

    def test_load_preserves_explicit_edge_ids(self, tmp_path):
        import json

        data = {
            "nodes": [{"id": 1, "lat": 0, "lon": 0}, {"id": 2, "lat": 0, "lon": 1}],
            "edges": [{"edge_id": 99, "from": 1, "to": 2, "base_time": 10, "distance": 100}],
        }
        p = tmp_path / "g.json"
        p.write_text(json.dumps(data))
        g = Graph()
        g.load_from_file(str(p))
        assert 99 in g.edges


# ------------------------------------------------------------------
# graph_to_dict
# ------------------------------------------------------------------


class TestGraphToDict:
    def test_round_trip_structure(self):
        g = simple_graph()
        d = g.graph_to_dict()
        assert "nodes" in d
        assert "edges" in d
        assert len(d["nodes"]) == 3
        assert len(d["edges"]) == 3
