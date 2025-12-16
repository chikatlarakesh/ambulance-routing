# Emergency Ambulance Routing (MVP)

## Run locally
1. create venv
   python -m venv venv
   source venv/bin/activate

2. install
   pip install -r requirements.txt

3. run
   uvicorn api.main:app --reload --port 8000

## Example requests

Route request:
curl -X POST "http://127.0.0.1:8000/route_ambulance" -H "Content-Type: application/json" -d '{
  "ambulance_id":"A1",
  "current_location":{"lat":12.97,"lon":77.59},
  "destination":{"lat":12.965,"lon":77.60}
}'

Traffic snapshot:
curl -X POST "http://127.0.0.1:8000/traffic_snapshot" -H "Content-Type: application/json" -d @examples/traffic_snapshot.json

## Push to GitHub
git init
git add .
git commit -m "initial: fastapi scaffold + routing core"
# create repo on github then:
git remote add origin git@github.com:<you>/ambulance-routing.git
git push -u origin main
