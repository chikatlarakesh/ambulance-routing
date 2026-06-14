# Performance Benchmark Report

*Generated: 2026-06-14T05:12:03Z*

## Graphs

| Graph | Nodes | Edges |
|-------|-------|-------|
| Small | 4 | 5 |
| Large | 200 | 666 |

## Results

| Scenario | Routes | Algorithm | Total (ms) | Per route (ms) | Solved |
|----------|--------|-----------|-----------|----------------|--------|
| Small graph (4 nodes) | 100 | dijkstra | 0.3 | 0.003 | 55 |
| Small graph (4 nodes) | 100 | a_star | 0.7 | 0.007 | 55 |
| Small graph (4 nodes) | 1000 | dijkstra | 3.3 | 0.003 | 523 |
| Small graph (4 nodes) | 1000 | a_star | 6.2 | 0.006 | 523 |
| Large graph (200 nodes) | 100 | dijkstra | 16.7 | 0.167 | 100 |
| Large graph (200 nodes) | 100 | a_star | 12.8 | 0.128 | 100 |
| Large graph (200 nodes) | 1000 | dijkstra | 189.9 | 0.190 | 991 |
| Large graph (200 nodes) | 1000 | a_star | 139.8 | 0.140 | 991 |

## Observations

- Both algorithms are **O(E log V)** with a priority queue; differences are constant-factor.
- A\* prunes the search space using the haversine heuristic, giving faster wall-clock times on sparse large graphs where the straight-line distance to the target guides exploration.
- On the 4-node small graph the graphs are so small that overhead dominates and results are essentially identical.
- Sub-millisecond per-route performance means the bottleneck in production will be I/O, not routing computation.

## How to reproduce

```bash
PYTHONPATH=. python benchmarks/benchmark.py
```
