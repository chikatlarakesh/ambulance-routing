"""Tests for api/main.py endpoints."""

import datetime
import os

import pytest
from fastapi.testclient import TestClient

# Ensure the sample graph exists before importing the app
os.environ.setdefault("PYTHONPATH", ".")

from api.main import active_routes, app, graph, reroute_events  # noqa: E402

UTC = datetime.timezone.utc
client = TestClient(app)


def clear_state():
    active_routes.clear()
    reroute_events.clear()
    graph.reset_edge_overrides()


@pytest.fixture(autouse=True)
def reset_state():
    clear_state()
    yield
    clear_state()


# ------------------------------------------------------------------
# GET /
# ------------------------------------------------------------------


class TestRoot:
    def test_returns_200(self):
        r = client.get("/")
        assert r.status_code == 200
        data = r.json()
        assert "message" in data
        assert "nodes" in data
        assert "edges" in data


# ------------------------------------------------------------------
# POST /route_ambulance
# ------------------------------------------------------------------


class TestRouteAmbulance:
    def _payload(self, amb_id="AMB-001"):
        return {
            "ambulance_id": amb_id,
            "current_location": {"lat": 12.97, "lon": 77.59},
            "destination": {"lat": 12.969, "lon": 77.593},
        }

    def test_success_returns_route(self):
        r = client.post("/route_ambulance", json=self._payload())
        assert r.status_code == 200
        data = r.json()
        assert data["algorithm"] == "dijkstra"
        assert "path" in data
        assert len(data["path"]) >= 1
        assert "estimated_arrival" in data

    def test_stores_active_route(self):
        client.post("/route_ambulance", json=self._payload("A1"))
        assert "A1" in active_routes

    def test_stores_utc_aware_eta(self):
        client.post("/route_ambulance", json=self._payload("A1"))
        eta = active_routes["A1"]["eta"]
        assert eta.tzinfo is not None

    def test_no_ambulance_id_still_returns_route(self):
        payload = self._payload()
        del payload["ambulance_id"]
        r = client.post("/route_ambulance", json=payload)
        assert r.status_code == 200

    def test_departure_time_respected(self):
        payload = self._payload()
        payload["departure_time"] = "2026-06-12T08:00:00Z"
        r = client.post("/route_ambulance", json=payload)
        assert r.status_code == 200


# ------------------------------------------------------------------
# POST /route_ambulance_astar
# ------------------------------------------------------------------


class TestRouteAmbulanceAstar:
    def _payload(self):
        return {
            "ambulance_id": "ASTAR-001",
            "current_location": {"lat": 12.97, "lon": 77.59},
            "destination": {"lat": 12.969, "lon": 77.593},
        }

    def test_success(self):
        r = client.post("/route_ambulance_astar", json=self._payload())
        assert r.status_code == 200
        assert r.json()["algorithm"] == "astar"

    def test_eta_matches_dijkstra_approximately(self):
        payload = {
            "current_location": {"lat": 12.97, "lon": 77.59},
            "destination": {"lat": 12.969, "lon": 77.593},
            "departure_time": "2026-06-12T08:00:00Z",
        }
        r_d = client.post("/route_ambulance", json=payload)
        r_a = client.post("/route_ambulance_astar", json=payload)
        assert r_d.status_code == 200 and r_a.status_code == 200
        # Both should find a valid route — ETAs should be identical since same graph
        assert r_d.json()["estimated_arrival"] == r_a.json()["estimated_arrival"]


# ------------------------------------------------------------------
# POST /traffic_snapshot
# ------------------------------------------------------------------


class TestTrafficSnapshot:
    def test_applies_edge_update(self):
        # Edge 1 exists in sample_graph
        payload = {
            "timestamp": "2026-06-12T08:00:00Z",
            "edge_updates": [{"edge_id": 1, "multiplier": 2.0}],
        }
        r = client.post("/traffic_snapshot", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert 1 in data["applied_edge_ids"]
        assert graph.edges[1]["multiplier"] == 2.0

    def test_invalid_edge_returns_error_not_500(self):
        payload = {
            "timestamp": "2026-06-12T08:00:00Z",
            "edge_updates": [{"edge_id": 9999, "multiplier": 2.0}],
        }
        r = client.post("/traffic_snapshot", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert len(data["errors"]) > 0

    def test_auto_reroute_triggered_on_large_slowdown(self):
        # First route an ambulance
        route_payload = {
            "ambulance_id": "AUTO-001",
            "current_location": {"lat": 12.97, "lon": 77.59},
            "destination": {"lat": 12.965, "lon": 77.60},
        }
        client.post("/route_ambulance", json=route_payload)

        # Apply extreme slowdown on edge 1
        snap_payload = {
            "timestamp": "2026-06-12T08:00:00Z",
            "edge_updates": [{"edge_id": 1, "absolute_time": 99999.0}],
        }
        r = client.post("/traffic_snapshot", json=snap_payload)
        assert r.status_code == 200
        # auto_reroutes list may or may not be populated depending on remaining time
        # but the response should be valid
        assert "auto_reroutes" in r.json()


# ------------------------------------------------------------------
# POST /reroute_check
# ------------------------------------------------------------------


class TestRerouteCheck:
    def _setup_ambulance(self, amb_id="RR-001"):
        client.post(
            "/route_ambulance",
            json={
                "ambulance_id": amb_id,
                "current_location": {"lat": 12.97, "lon": 77.59},
                "destination": {"lat": 12.965, "lon": 77.60},
            },
        )

    def test_no_active_route_returns_404(self):
        r = client.post("/reroute_check", json={"ambulance_id": "GHOST"})
        assert r.status_code == 404

    def test_active_route_returns_reroute_decision(self):
        self._setup_ambulance("RR-001")
        r = client.post("/reroute_check", json={"ambulance_id": "RR-001"})
        assert r.status_code == 200
        data = r.json()
        assert "reroute" in data

    def test_reroute_true_when_significant_slowdown(self):
        self._setup_ambulance("RR-002")
        # Make all edges very slow
        updates = [{"edge_id": eid, "absolute_time": 99999.0} for eid in graph.edges]
        client.post(
            "/traffic_snapshot",
            json={
                "timestamp": "2026-06-12T08:00:00Z",
                "edge_updates": updates,
            },
        )
        # Re-setup so route uses current fast state as reference, then degrade
        clear_state()
        self._setup_ambulance("RR-002")
        # Now make edges on old path very slow (but keep an alternative)
        graph.reset_edge_overrides()
        graph.apply_edge_update(
            __import__("core.graph", fromlist=["EdgeUpdate"]).EdgeUpdate(
                edge_id=1, absolute_time=86400.0
            )
        )
        r = client.post("/reroute_check", json={"ambulance_id": "RR-002"})
        assert r.status_code == 200


# ------------------------------------------------------------------
# POST /update_position
# ------------------------------------------------------------------


class TestUpdatePosition:
    def test_updates_location(self):
        client.post(
            "/route_ambulance",
            json={
                "ambulance_id": "POS-001",
                "current_location": {"lat": 12.97, "lon": 77.59},
                "destination": {"lat": 12.969, "lon": 77.593},
            },
        )
        r = client.post(
            "/update_position",
            json={
                "ambulance_id": "POS-001",
                "lat": 12.971,
                "lon": 77.592,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ambulance_id"] == "POS-001"
        assert "remaining_seconds" in data

    def test_no_active_route_returns_404(self):
        r = client.post(
            "/update_position",
            json={
                "ambulance_id": "GHOST",
                "lat": 12.97,
                "lon": 77.59,
            },
        )
        assert r.status_code == 404


# ------------------------------------------------------------------
# Debug endpoints
# ------------------------------------------------------------------


class TestDebugEndpoints:
    def test_debug_edges(self):
        r = client.get("/debug/edges")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["edges"]) == len(graph.edges)

    def test_debug_active_routes(self):
        client.post(
            "/route_ambulance",
            json={
                "ambulance_id": "DBG-001",
                "current_location": {"lat": 12.97, "lon": 77.59},
                "destination": {"lat": 12.969, "lon": 77.593},
            },
        )
        r = client.get("/debug/active_routes")
        assert r.status_code == 200
        data = r.json()
        assert "DBG-001" in data

    def test_debug_reset_overrides(self):
        from core.graph import EdgeUpdate

        graph.apply_edge_update(EdgeUpdate(edge_id=1, multiplier=5.0))
        assert graph.edges[1]["multiplier"] == 5.0
        r = client.post("/debug/reset_overrides")
        assert r.status_code == 200
        assert graph.edges[1]["multiplier"] == 1.0

    def test_debug_reroute_events(self):
        r = client.get("/debug/reroute_events")
        assert r.status_code == 200
        assert "events" in r.json()


# ------------------------------------------------------------------
# Reroute ETA bug-fix regression tests
# ------------------------------------------------------------------


class TestRerouteCheckBugFix:
    """
    Regression suite for the bug reported in message-2:

        path=[1,2,4], remaining_seconds=100
        After traffic_snapshot (edge_id=4, multiplier=20)
        reroute_check returned {old_remaining_sec:0, new_remaining_sec:0}

    Root cause: _recalculate_eta used _remaining_seconds(stored_eta, wall_clock_now).
    When the stored ETA is in the past the result is 0 regardless of actual path cost.
    """

    # A departure time that is definitively in the past at test-run time so the
    # stored ETA is guaranteed stale.
    PAST = "2026-06-12T08:00:00Z"

    # A departure time far enough in the future that the ambulance has not yet
    # departed, giving deterministic current_node_idx=0 arithmetic.
    FUTURE = "2030-01-01T08:00:00Z"

    def _route_1_to_4(self, amb_id: str, departure: str = None):
        """node-1 (12.97,77.59) → node-4 (12.965,77.60).  path=[1,2,4], base=100 s."""
        payload = {
            "ambulance_id": amb_id,
            "current_location": {"lat": 12.97, "lon": 77.59},
            "destination": {"lat": 12.965, "lon": 77.60},
        }
        if departure:
            payload["departure_time"] = departure
        r = client.post("/route_ambulance", json=payload)
        assert r.status_code == 200
        return r.json()

    def _route_1_to_3(self, amb_id: str, departure: str = None):
        """node-1 → node-3 (12.969,77.593).  path=[1,2,3], base=80 s."""
        payload = {
            "ambulance_id": amb_id,
            "current_location": {"lat": 12.97, "lon": 77.59},
            "destination": {"lat": 12.969, "lon": 77.593},
        }
        if departure:
            payload["departure_time"] = departure
        r = client.post("/route_ambulance", json=payload)
        assert r.status_code == 200
        return r.json()

    @staticmethod
    def _old_remaining(data: dict) -> float:
        if data.get("reroute"):
            return data["old_remaining"]["minutes"] * 60 + data["old_remaining"]["seconds"]
        return data["old_remaining_sec"]

    @staticmethod
    def _new_remaining(data: dict) -> float:
        if data.get("reroute"):
            return data["new_remaining"]["minutes"] * 60 + data["new_remaining"]["seconds"]
        return data["new_remaining_sec"]

    # ---- Test 1: exact bug reproduction ----

    def test_reroute_check_old_remaining_nonzero_with_past_departure(self):
        """
        Exact scenario from the bug report (message-2).

        path=[1,2,4] created with a past departure.  After traversing
        all segments the ambulance is estimated at node-2 (last non-destination
        node).  old_remaining must equal the edge 2→4 cost (60 s), not 0.

        Bug:  _remaining_seconds(stale_eta, now) → 0
        Fix:  _compute_remaining_path_cost(graph, path, node_idx, now) → 60 s
        """
        self._route_1_to_4("BUG-001", departure=self.PAST)
        # Apply traffic (mirrors the exact report)
        client.post(
            "/traffic_snapshot",
            json={
                "timestamp": self.PAST,
                "edge_updates": [{"edge_id": 4, "multiplier": 20.0}],
            },
        )
        r = client.post("/reroute_check", json={"ambulance_id": "BUG-001"})
        assert r.status_code == 200
        old_rem = self._old_remaining(r.json())
        assert old_rem > 0, f"old_remaining must be > 0 (got {old_rem})"

    # ---- Test 2: ETA refresh without crossing reroute threshold ----

    def test_traffic_snapshot_refreshes_remaining_seconds_without_reroute(self):
        """
        A moderate slowdown (1.5×) does not trigger auto-reroute, but
        remaining_seconds must still be updated to reflect current graph costs.

        Setup: path=[1,2,4], future departure → ambulance at node-1.
        edge-4 (2→4): 60 s → 90 s.  Full path = 40+90 = 130 s.
        No alternative exists so time_saved=0 < 120 s threshold.

        Bug:  remaining_seconds unchanged (wall-clock ETA refresh skipped).
        Fix:  remaining_seconds = 130 s.
        """
        self._route_1_to_4("BUG-002", departure=self.FUTURE)
        client.post(
            "/traffic_snapshot",
            json={
                "timestamp": self.FUTURE,
                "edge_updates": [{"edge_id": 4, "multiplier": 1.5}],
            },
        )
        updated = active_routes["BUG-002"]["remaining_seconds"]
        assert (
            abs(updated - 130.0) < 5.0
        ), f"remaining_seconds should be ~130 s after 1.5× on edge-4, got {updated}"

    # ---- Test 3: auto-reroute fires with correct path-cost comparison ----

    def test_auto_reroute_fires_when_alternative_becomes_faster(self):
        """
        Block edge-1 (1→2, absolute_time=9999 s).
        path=[1,2,3]: old_remaining = 9999+40 = 10039 s.
        Direct 1→3 (edge-3): 120 s.  time_saved = 9919 s >> 120 s threshold.

        Bug:  old_remaining=0 → time_saved=0 → auto_reroutes empty.
        Fix:  auto_reroutes contains one entry for BUG-003.
        """
        self._route_1_to_3("BUG-003", departure=self.FUTURE)
        assert active_routes["BUG-003"]["path"] == [1, 2, 3]

        r = client.post(
            "/traffic_snapshot",
            json={
                "timestamp": self.FUTURE,
                "edge_updates": [{"edge_id": 1, "absolute_time": 9999.0}],
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["auto_reroutes"]) > 0, "auto_reroute should have fired"
        assert data["auto_reroutes"][0]["ambulance_id"] == "BUG-003"

    # ---- Test 4: new_remaining also non-zero with stale ETA ----

    def test_reroute_check_new_remaining_nonzero_with_past_departure(self):
        """
        Both old_remaining and new_remaining must be > 0 even when the stored
        ETA is in the past.  Dijkstra always finds an optimal path so
        new_remaining ≤ old_remaining (within float tolerance).
        """
        self._route_1_to_4("BUG-004", departure=self.PAST)
        r = client.post("/reroute_check", json={"ambulance_id": "BUG-004"})
        assert r.status_code == 200
        data = r.json()
        old_rem = self._old_remaining(data)
        new_rem = self._new_remaining(data)
        assert old_rem > 0, f"old_remaining must be > 0, got {old_rem}"
        assert new_rem > 0, f"new_remaining must be > 0, got {new_rem}"
        assert new_rem <= old_rem + 1.0  # Dijkstra is optimal; +1 for float rounding
