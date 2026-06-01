# birdSpotter

Bird flock tracking server API. Accepts bird sighting reports via REST, groups them into flocks using spatiotemporal proximity, predicts destination cities, and sends email notifications to flock coordinators.

## Prerequisites

- **Python 3.11+**
- **Neo4j** — running on `localhost:7687` (default). See [Setup](#setup) for options.
- **Redis** — running on `localhost:6379` (default).

## Useful commands 
python load_cities.py --clean



## Setup

### 1. Clone and create virtual environment

```bash
cd birdSpotter
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate


cleand test data : python load_cities.py --clean
run tests :  python -m pytest 
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure credentials

Create a `.env` file with non-secret configuration:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j

NEO4J_TEST_URI=bolt://127.0.0.1:7688
NEO4J_TEST_USER=neo4j

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com

REDIS_HOST=localhost
REDIS_PORT=6379

V_MAX_KMH=100
SILENCE_WINDOW_HOURS=10
BEARING_TOLERANCE_DEG=30
```

Create a `pass.yaml` file with secrets (never commit this file):

```yaml
neo4j:
  password: your_neo4j_password

neo4j_test:
  password: your_test_neo4j_password

smtp:
  password: your_smtp_app_password
```

### 4. Initialize the database

```bash
python init_db.py
```

This creates Neo4j constraints and indexes for `Flock`, `Report`, `Coordinator`, and `City` nodes.

### 5. (Optional) Load city data

Load Polish cities from the GeoJSON dataset:

```bash
python load_cities.py
```

### 6. Start the server

```bash
uvicorn app.main:app --reload
```

The API is now available at **http://localhost:8000**.

## API Reference

### Health Check

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{"status": "ok"}
```

### Submit a Bird Sighting Report

```bash
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 52.23,
    "longitude": 21.01,
    "timestamp": "2026-06-10T12:00:00+00:00",
    "coordinator_email": "alice@example.com"
  }'
```

**Response:**
```json
{
  "report_id": "a1b2c3d4-...",
  "flock_id": "e5f6a7b8-...",
  "message": "Nowe stado e5f6a7b8"
}
```

- `"Nowe stado ..."` — a new flock was created
- `"Dołączono ..."` — the report was added to an existing flock

### Submit a Second Report (joins existing flock)

```bash
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 52.41,
    "longitude": 21.01,
    "timestamp": "2026-06-10T12:30:00+00:00",
    "coordinator_email": "bob@example.com"
  }'
```

Since the report is within `V_MAX_KMH` (100 km/h) and `SILENCE_WINDOW_HOURS` (10 h) of the first report, it joins the same flock.

### Submit a Report Too Far Away (creates new flock)

```bash
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 51.75,
    "longitude": 19.45,
    "timestamp": "2026-06-10T12:30:00+00:00",
    "coordinator_email": "charlie@example.com"
  }'
```

This report is ~500 km from the first flock — too far to join, so a new flock is created.

### Invalid Inputs (422 errors)

```bash
# Latitude out of range
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{"latitude": 100, "longitude": 21.01, "coordinator_email": "test@example.com"}'

# Invalid email
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{"latitude": 52.0, "longitude": 21.0, "coordinator_email": "not-an-email"}'

# Future timestamp
curl -X POST http://localhost:8000/api/report \
  -H "Content-Type: application/json" \
  -d '{"latitude": 52.0, "longitude": 21.0, "timestamp": "2099-01-01T00:00:00+00:00", "coordinator_email": "test@example.com"}'
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_TEST_URI` | `bolt://127.0.0.1:7688` | Test Neo4j URI |
| `NEO4J_TEST_USER` | `neo4j` | Test Neo4j username |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP server |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USER` | — | SMTP sender email |
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `V_MAX_KMH` | `100` | Max bird speed (km/h) for flock matching |
| `SILENCE_WINDOW_HOURS` | `10` | Time window for flock identification |
| `BEARING_TOLERANCE_DEG` | `30` | Angular tolerance for city prediction |

Secrets (`neo4j.password`, `neo4j_test.password`, `smtp.password`) are loaded from `pass.yaml`.

## Running Tests

```bash
# All tests
python -m pytest

# Only unit tests (no Docker container needed)
python -m pytest test_services.py test_models.py test_utils.py test_main.py test_neo4j_client.py

# Integration tests (auto-starts a test Neo4j container)
python -m pytest test_integration_submit_report.py -v
```

## Docker — Test Neo4j Container

The integration tests automatically start a dedicated Neo4j container on port 7688. You can also manage it manually:

```bash
# Start
docker run -d \
  --name birdspotter-test-neo4j \
  -p 7688:7687 -p 7475:7474 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:latest

# Stop
docker rm -f birdspotter-test-neo4j
```

Or use the convenience `docker-compose.yml`:

```bash
docker compose up -d
docker compose down
```

## Architecture

```
POST /api/report
  │
  ├─ 1. identify_or_create_flock()     → Flock node (or existing)
  ├─ 2. add_report_and_get_flock_info() → Report node, LAST_REPORT, Coordinator
  ├─ 3. predict_city()                  → Nearest city in bearing sector
  └─ 4. send_notification()             → Email to flock coordinators
```

**Neo4j graph model:**

```
(Flock)──[:HAS_REPORT]──> (Report)
(Flock)──[:LAST_REPORT]─> (Report)
(Flock)──[:NOTIFIED_OF]─> (Coordinator)
```
