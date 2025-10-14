from core.graph import Graph
from core.routing import dijkstra_route
import datetime

def test_simple_route():
    g = Graph()
    g.add_node(1, 0, 0)
    g.add_node(2, 0, 1)
    g.add_node(3, 1, 1)
    g.add_edge(1,2, 10, 100)
    g.add_edge(2,3, 10, 100)
    arrival, path, segs = dijkstra_route(g, 1, 3, datetime.datetime.utcnow())
    assert path == [1,2,3]
