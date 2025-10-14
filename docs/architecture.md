# Emergency Ambulance Routing API – Architecture Overview

## 1. Project Overview

The Emergency Ambulance Routing API calculates optimal routes for ambulances in real-time. It supports rerouting in response to traffic changes and aims to minimize travel time.

**Key Features (MVP):**

* Route calculation using **Time-Dependent Dijkstra**.
* Simple reroute logic to adapt to traffic updates.
* Traffic snapshot API to simulate dynamic conditions.

---

## 2. Folder Structure

```
ambulance-routing/
│
├─ api/
│  ├─ main.py         # FastAPI endpoints
│  └─ schemas.py      # Pydantic models
│
├─ core/
│  ├─ graph.py        # Graph structure, nodes, edges
│  └─ routing.py      # Algorithms (Dijkstra, TD-Dijkstra)
│
├─ examples/
│  └─ sample_graph.json  # Sample city graph
│
├─ tests/
│  └─ test_routing.py    # Unit tests
│
├─ docs/
│  ├─ architecture.md
│  └─ DEMO.md
│
└─ .github/workflows/
   └─ python-ci.yml      # GitHub Actions CI
```

---

## 3. Core Components

### 3.1 Graph Representation

* **Nodes**: locations (latitude & longitude)
* **Edges**: roads with time-dependent travel times
* **Edge Updates**: multipliers applied via traffic snapshots

### 3.2 Routing Algorithms

* **Time-Dependent Dijkstra** (MVP)

  * Considers travel time varying by departure time.
  * Supports reroute decisions if traffic changes.
* **Future / A***: will add heuristic-based pathfinding (Euclidean/Haversine).

---

## 4. API Endpoints

| Endpoint            | Method | Input                                                      | Output                              | Description                              |
| ------------------- | ------ | ---------------------------------------------------------- | ----------------------------------- | ---------------------------------------- |
| `/`                 | GET    | None                                                       | Status message                      | Health check / running API               |
| `/route_ambulance`  | POST   | Ambulance ID, origin, destination, optional departure_time | Route info, ETA, segments, geometry | Calculate optimal route for an ambulance |
| `/traffic_snapshot` | POST   | Timestamp, edge updates                                    | Status OK, applied count            | Update traffic conditions dynamically    |
| `/reroute_check`    | POST   | Ambulance ID, current_time                                 | New route if ETA improves           | Trigger reroute check based on traffic   |

---

## 5. Design Choices

* **Python + FastAPI**: lightweight, fast API framework, easy to demonstrate.
* **Pydantic**: ensures strict input validation for endpoints.
* **Graph abstraction**: clean separation of nodes, edges, and algorithms.
* **UUIDs for routes**: unique route identifiers for tracking.
* **Time-dependent routing**: simulates realistic city conditions.

---

## 6. Future Extensions / High-Impact Features

* Redis caching for frequent route lookups.
* React + Leaflet front-end for live route visualization.
* Multi-ambulance optimization for fastest dispatch.
* Metrics dashboard for ETA accuracy and route changes.
* Integration with real city data using `osmnx` / OSM.

---
