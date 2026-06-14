# Emergency Ambulance Routing System

A production-quality Python backend for real-time ambulance routing with time-dependent Dijkstra,
A*, dynamic traffic updates, automatic rerouting, and virtual-time simulation.

---

## Quick Start

```bash
git clone https://github.com/chikatlarakesh/ambulance-routing
cd ambulance-routing
python -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
PYTHONPATH=. uvicorn api.main:app --reload
```

API docs: http://localhost:8000/docs

### Docker (single command)

```bash
docker-compose up --build
```

API docs: http://localhost:8000/docs

---

## Architecture

```
Client
  |
  v
FastAPI  (api/main.py)
  |  +-- Middleware: CORS, request-ID, timing, exception handler
  |
  +-- /api/v1/route_ambulance        --> time_dependent_dijkstra()
  +-- /api/v1/route_ambulance_astar  --> a_star_route()
  +-- /api/v1/traffic_snapshot       --> graph.apply_edge_update() + auto-reroute
  +-- /api/v1/reroute_check          --> _recalculate_eta()
  +-- /api/v1/update_position
  +-- /api/v1/debug/*
  |
  +-- Graph      (core/graph.py)       nodes, directed edges, time buckets, multipliers
  +-- Routing    (core/routing.py)     Dijkstra / A* / time-dependent helpers
  +-- Simulator  (core/simulator.py)   virtual-time simulation engine
  +-- Config     (core/config.py)      all tunable constants, env-var overrides
  +-- Logging    (core/logging_config.py)  structured logs, JSON in production
```

Full Mermaid diagrams (routing flow, traffic flow, simulation flow, class diagram):
see [docs/architecture.md](docs/architecture.md).

---

## Folder Layout

| Path | Purpose |
|------|---------|
| `api/main.py` | FastAPI app, middleware, all HTTP endpoints |
| `api/schemas.py` | Pydantic request/response models with input validation |
| `core/graph.py` | Graph data structure; edge travel time; traffic updates |
| `core/routing.py` | Dijkstra, A*, haversine heuristic, UTC helpers |
| `core/simulator.py` | Virtual-time simulation engine with traffic injection |
| `core/config.py` | All magic numbers — overridable via environment variables |
| `core/logging_config.py` | Standard-format (dev) / JSON-format (prod) logging |
| `benchmarks/benchmark.py` | Algorithm micro-benchmarks (Dijkstra vs A*) |
| `benchmarks/load_test.py` | HTTP stress test (httpx async, 100–1000 concurrency) |
| `tests/` | 87 pytest tests across all modules |
| `examples/` | Sample graph JSON files |
| `docs/` | Architecture diagrams and benchmark report |

---

## Routing Algorithms

### Time-Dependent Dijkstra

True time-dependent label-setting algorithm (FIFO). At each edge relaxation the travel
cost is evaluated at the **arrival time at that node**, not at the global departure time.
This means an ambulance departing at 07:45 and reaching a junction at 08:02 pays
rush-hour cost for the next edge.

**Complexity:** O((V + E) log V)

### A* with Haversine Heuristic

Uses great-circle distance / max_speed (15 m/s) as an admissible lower-bound heuristic.
Prunes explored nodes that cannot possibly improve on the best known ETA.
Returns **identical ETAs** to Dijkstra on the same graph; generally faster on large sparse
graphs where the straight-line distance guides exploration away from dead ends.

### Comparison

| Metric | Dijkstra | A* |
|--------|----------|----|
| Small graph, 1000 routes | ~2 ms | ~5 ms |
| Large graph (200 nodes), 1000 routes | ~145 ms | ~115 ms |
| Correctness vs Dijkstra | baseline | identical ETA |

See [docs/benchmark_report.md](docs/benchmark_report.md) for full results.

---

## Traffic Model

### Edge weight priority (highest wins)

1. `absolute_time` — set via `/traffic_snapshot`; bypasses all other costs
2. Matching `time_bucket` (seconds-of-day in range) × `multiplier`
3. `base_time` × `multiplier`

### Rules

- Multiplier **replaces** (does not accumulate) on each update.
- Reset via `POST /api/v1/debug/reset_overrides`.

---

## Reroute Logic

A reroute is triggered when either condition is met:

```
old_remaining - new_remaining >= REROUTE_THRESHOLD_SEC   (default: 120 s)

OR

any of next SLOWDOWN_LOOKAHEAD (3) segments has:
    current_travel_time / baseline_travel_time > SLOWDOWN_RATIO (1.5)
```

`old_remaining` is computed from **current graph costs** (not the stale stored ETA),
ensuring the comparison is always accurate even for routes created in the past.

---

## Simulator

Run a complete virtual-time simulation without any real sleeping:

```python
from core.simulator import SimulationEngine, TrafficInjection
from core.graph import EdgeUpdate, Graph
import datetime

g = Graph()
g.load_from_file("examples/sample_graph.json")

engine = SimulationEngine(g)
result = engine.run(
    ambulance_id="AMB-001",
    start_node=1,
    end_node=3,
    depart_dt=datetime.datetime(2026, 6, 12, 8, 0, 0, tzinfo=datetime.timezone.utc),
    traffic_injections=[
        TrafficInjection(
            trigger_at=datetime.datetime(2026, 6, 12, 8, 0, 40, tzinfo=datetime.timezone.utc),
            edge_updates=[EdgeUpdate(edge_id=2, multiplier=3.0)],
            label="Heavy congestion on edge 2",
        )
    ],
)
print(result.log())
```

Simulation events: `DEPART`, `SEGMENT`, `TRAFFIC`, `REROUTE`, `ARRIVE`.

---

## API Reference

> Canonical endpoints are under `/api/v1/`. Legacy root-level paths are preserved as
> backward-compatible aliases.

### POST /api/v1/route_ambulance

```json
{
  "ambulance_id": "AMB-001",
  "current_location": {"lat": 12.97, "lon": 77.59},
  "destination": {"lat": 12.969, "lon": 77.593},
  "departure_time": "2026-06-12T08:00:00Z"
}
```

### POST /api/v1/route_ambulance_astar

Same schema. Returns `"algorithm": "astar"`.

### POST /api/v1/traffic_snapshot

```json
{
  "timestamp": "2026-06-12T08:05:00Z",
  "edge_updates": [
    {"edge_id": 2, "multiplier": 1.5},
    {"edge_id": 3, "absolute_time": 300.0}
  ]
}
```

Automatically evaluates rerouting for all active ambulances.

### POST /api/v1/reroute_check

```json
{"ambulance_id": "AMB-001"}
```

### POST /api/v1/update_position

```json
{
  "ambulance_id": "AMB-001",
  "lat": 12.971,
  "lon": 77.592,
  "timestamp": "2026-06-12T08:01:30Z"
}
```

### Debug Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v1/debug/edges | All nodes/edges with current multipliers |
| GET | /api/v1/debug/active_routes | All active ambulances and their state |
| POST | /api/v1/debug/reset_overrides | Reset all (or one) edge overrides |
| GET | /api/v1/debug/reroute_events | Full reroute event history |

---

## Testing

```bash
PYTHONPATH=. python -m pytest tests/ -v --cov=api --cov=core
```

| File | Coverage |
|------|----------|
| `tests/test_graph.py` | Node/edge CRUD, travel time, updates, file loading |
| `tests/test_routing.py` | Dijkstra, A*, UTC helpers, time-dependent routing |
| `tests/test_api.py` | All endpoints, happy path + failure path + reroute regression |
| `tests/test_simulator.py` | Movement, traffic injection, rerouting, arrival |

87 tests, 0 failures.

---

## Configuration

All magic numbers are in `core/config.py` and overridable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REROUTE_THRESHOLD_SEC` | `120` | Minimum time saving to trigger auto-reroute |
| `SLOWDOWN_LOOKAHEAD` | `3` | Upcoming segments to inspect for slowdowns |
| `SLOWDOWN_RATIO` | `1.5` | Travel time ratio threshold for slowdown detection |
| `MAX_EDGE_UPDATES_PER_SNAPSHOT` | `500` | Max edge updates per traffic_snapshot |
| `AMBULANCE_ID_MAX_LEN` | `64` | Max length for ambulance IDs |
| `GRAPH_PATH` | `""` | Override graph file path |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG / INFO / WARNING / ERROR |
| `APP_ENV` | `development` | `development` / `testing` / `production` |
| `PORT` | `8000` | Port for Docker / uvicorn |

---

## Benchmarks

```bash
PYTHONPATH=. python benchmarks/benchmark.py
```

Load test (requires running server):

```bash
python benchmarks/load_test.py --url http://localhost:8000 --concurrency 100 500 1000
```

---

## Code Quality

```bash
black api/ core/ tests/ benchmarks/          # format
isort --profile black api/ core/ tests/      # sort imports
flake8 api/ core/ tests/ benchmarks/         # lint
mypy api/ core/                              # type check
```

Config in `pyproject.toml` and `.flake8`.

---

## How to Extend

### Add a new routing algorithm

1. Implement `my_algo(graph, source, target, depart_dt)` in `core/routing.py`.
   Return `(arrival_dt, path, per_segment_times)` — same signature as `dijkstra_route`.
2. Add a new endpoint in `api/main.py` calling `_do_route(req, "my_algo")` after registering
   the function name in `_do_route`.

### Add a new graph data source

1. Implement a loader function in `core/graph.py` (e.g., `load_from_osm`).
2. Wire it to `GRAPH_PATH` in config or add a new startup option in `api/main.py`.

### Change reroute threshold at runtime

Set the `REROUTE_THRESHOLD_SEC` environment variable before starting the server.
The config module reads it at import time.

---

## Future Roadmap

- WebSocket live position streaming
- OpenStreetMap graph import
- Multi-ambulance dispatch optimisation
- PostgreSQL persistence for active routes
- ETA confidence intervals from historical data
- gRPC interface for fleet management integration
