# Kitsap Commute Helper

A multi-server MCP application that helps Kitsap Peninsula residents plan ferry commutes, manage events, and track travel expenses — all from Claude Desktop.

## Architecture

Three FastMCP servers, each with a focused role:

| Server | Purpose | Tools |
|---|---|---|
| `wsdot_server.py` | Live ferry data & travel estimates | `find_nearest_terminals`, `get_ferry_schedule`, `get_todays_sailings`, `get_ferry_fare`, `get_drive_time`, `estimate_total_travel`, `generate_expense_estimate` |
| `events_write_server.py` | Create events & save travel plans | `create_event`, `save_travel_plan` |
| `events_read_server.py` | AI-powered event search via Elastic Agent Builder | `search_events` |

## Project Structure

```
kitsap-commute-helper/
├── wsdot_server.py            # MCP server: ferry schedules, fares, travel estimates
├── events_write_server.py     # MCP server: event creation and travel plan storage
├── events_read_server.py      # MCP server: natural language event search
├── elastic_agent_example.py   # Elastic Agent Builder client
├── utilities.py               # Shared utilities (haversine, datetime parsing)
├── config.py                  # Centralized configuration
│
├── data/
│   ├── ferry_terminals.json   # 7 ferry terminals with geocoded locations
│   └── sample_events.json     # Sample tech events for demo/testing
│
└── setup/
    └── elasticsearch_setup.py # One-time Elasticsearch + Kibana setup
```

## Getting Started

### Prerequisites

- Python 3.11+
- [Elastic Cloud Serverless](https://cloud.elastic.co) deployment
- WSDOT API key — [register here](https://www.wsdot.wa.gov/Traffic/api/)
- Google Maps API key with Directions + Geocoding enabled
- Kibana Agent Builder agent configured with ES|QL tools (see setup below)

### 1. Install dependencies

```bash
pip install elasticsearch fastmcp pydantic python-dotenv requests httpx
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
WSDOT_API_KEY=your_key
GOOGLE_MAPS_API_KEY=your_key

ELASTIC_ENDPOINT=https://your-deployment.es.us-east-1.aws.elastic.cloud
ELASTIC_API_KEY=your_api_key
EVENT_INDEX=events

KIBANA_API_KEY=your_kibana_api_key
ELASTIC_AGENT_ID=your_agent_builder_agent_id
```

`KIBANA_URL` is derived automatically from `ELASTIC_ENDPOINT` (`.es.` → `.kb.`).

### 3. Set up Elasticsearch (first time only)

```bash
# Run all setup steps: EIS endpoints, index, ES|QL tools, sample data
python setup/elasticsearch_setup.py --all

# Or individually:
python setup/elasticsearch_setup.py --create-endpoints   # EIS inference + reranker
python setup/elasticsearch_setup.py --create-index       # events index with semantic_text
python setup/elasticsearch_setup.py --create-tools       # Kibana Agent Builder ES|QL tools
python setup/elasticsearch_setup.py --load-sample-data   # load sample_events.json
```

### 4. Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wsdot-ferry": {
      "command": "/path/to/python3",
      "args": ["/path/to/kitsap-commute-helper/wsdot_server.py"]
    },
    "events-write": {
      "command": "/path/to/python3",
      "args": ["/path/to/kitsap-commute-helper/events_write_server.py"]
    },
    "events-read": {
      "command": "/path/to/python3",
      "args": ["/path/to/kitsap-commute-helper/events_read_server.py"]
    }
  }
}
```

Use full absolute paths. Find your Python path with `which python3`.

### 4b. Run with Docker

As an alternative to running servers directly with Python, you can use Docker.

#### Build the image

```bash
docker compose build
```

#### Run each server

```bash
docker compose run wsdot-server
docker compose run events-write-server
docker compose run events-read-server
```

Each server runs as a stdio MCP server inside the container. To connect Claude Desktop to the containerized servers, use `docker compose run` as the command:

```json
{
  "mcpServers": {
    "wsdot-ferry": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/kitsap-commute-helper/docker-compose.yml", "run", "--rm", "wsdot-server"]
    },
    "events-write": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/kitsap-commute-helper/docker-compose.yml", "run", "--rm", "events-write-server"]
    },
    "events-read": {
      "command": "docker",
      "args": ["compose", "-f", "/path/to/kitsap-commute-helper/docker-compose.yml", "run", "--rm", "events-read-server"]
    }
  }
}
```

Replace `/path/to/kitsap-commute-helper` with the absolute path to your project directory. Environment variables are loaded from `.env` automatically via `docker-compose.yml`.

---

## Features

### Ferry & Commute Planning (`wsdot_server.py`)

- **Live schedules** — calls WSDOT Ferries API directly, always current
- **Correct terminal pairs** — Southworth→Fauntleroy, Bremerton→Seattle, Kingston→Edmonds, etc.
- **Crossing times** — hardcoded per route (WSDOT API doesn't return this field)
- **Door-to-door estimates** — drive to terminal + crossing + drive to destination
- **Ferry fares** — live WSDOT Fares API; understands eastbound=paid, westbound=free
- **Mileage cost** — $0.70/mile (IRS standard rate) via Google Maps distance

### Event Management

**Write (`events_write_server.py`):**
- `create_event` — indexes a new event; `description` auto-embeds via EIS + jina-embeddings-v5
- `save_travel_plan` — stores a full expense estimate on an event document, with optional `choice` field recording the route actually taken

**Read (`events_read_server.py`):**
- `search_events` — forwards natural language queries to Elastic Agent Builder, which runs ES|QL tools against the index and returns a natural language answer
- Supports multi-turn conversation via `conversation_id`

### Expense Tracking

`generate_expense_estimate` computes ferry fare + mileage for every viable route from your origin and returns a `travel_plan` object. `save_travel_plan` embeds that plan directly in the event document — no separate index needed.

```
travel_plan
├── origin, destination, trip_date, calculated_at
├── recommended_route
├── choice { route, total_cost }    ← what you actually took
└── routes[]
    ├── type (ferry / drive)
    ├── departure_terminal, arrival_terminal
    ├── drive_to_terminal_minutes, crossing_time_minutes, drive_from_terminal_minutes
    ├── total_minutes
    ├── ferry_fare, mileage_cost, total_cost
```

---

## Elasticsearch Setup Details

The events index uses `semantic_text` for zero-config embeddings:

- **Inference endpoint**: `jina-embeddings-v5-text-small` via Elastic Inference Service
- **Reranker endpoint**: `jina-reranker-v3` via EIS
- `description` uses `copy_to: description_vector` — embedding happens automatically on ingest
- ES|QL tools are registered in Kibana Agent Builder for structured queries

---

## Notes

- Ferry terminal locations are static (`data/ferry_terminals.json`) — updated only when terminals open or move
- Ferry schedules are fetched live from WSDOT on every request — always current
- Sample events cover March–June 2026 and are synthetic demo data
- No frontend — interact via Claude Desktop or any MCP-compatible client
