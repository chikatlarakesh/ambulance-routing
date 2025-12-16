# 1️⃣ Start API
uvicorn api.main:app --reload --port 8000

# 2️⃣ Route ambulance
curl -X POST "http://127.0.0.1:8000/route_ambulance" \
-H "Content-Type: application/json" \
-d '{ "ambulance_id": "A1", "current_location": {"lat": 12.97,"lon": 77.59}, "destination": {"lat":12.965,"lon":77.6} }'

# 3️⃣ Inject traffic snapshot
curl -X POST "http://127.0.0.1:8000/traffic_snapshot" \
-H "Content-Type: application/json" \
-d '{ "timestamp": "2025-10-14T09:00:00Z", "edge_updates": [{"edge_id":1,"multiplier":1.5}] }'

# 4️⃣ Reroute check
curl -X POST "http://127.0.0.1:8000/reroute_check" \
-H "Content-Type: application/json" \
-d '{ "ambulance_id":"A1","current_time":"2025-10-14T10:04:37Z"}'
