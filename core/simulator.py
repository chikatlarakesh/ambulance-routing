import time
import requests

def simulate_ambulance(ambulance_id, route_id, segments):
    for seg in segments:
        print(f"Ambulance moving from {seg['start_node']} to {seg['end_node']}")
        time.sleep(1)  # simulate travel
        if seg['edge_id'] == 2:
            # inject traffic
            traffic_data = {
                "timestamp": "2025-10-14T10:05:00Z",
                "edge_updates": [{"edge_id": seg['edge_id'], "multiplier": 1.5}]
            }
            requests.post("http://127.0.0.1:8000/traffic_snapshot", json=traffic_data)
            # check reroute
            reroute_resp = requests.post("http://127.0-0.1:8000/reroute_check",
                                         json={"ambulance_id": ambulance_id, "current_time": "2025-10-14T10:05:00Z"})
            print("Reroute response:", reroute_resp.json())
