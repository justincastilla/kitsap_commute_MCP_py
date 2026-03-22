# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kitsap Commute Helper is a **three-server MCP application** that helps Kitsap Peninsula residents plan ferry commutes, manage events, and track travel expenses. All servers run as stdio-based MCP servers for Claude Desktop.

1. **`wsdot_server.py`** — Live ferry schedules, fares, drive times, and expense estimates
2. **`events_write_server.py`** — Create events and save travel plans to Elasticsearch
3. **`events_read_server.py`** — Natural language event search via Elastic Agent Builder

## Core Architecture

### Configuration System

All environment variables flow through **`config.py`**:
- API keys: `WSDOT_API_KEY`, `GOOGLE_MAPS_API_KEY`
- Elasticsearch: `ELASTIC_ENDPOINT`, `ELASTIC_API_KEY`, `EVENT_INDEX`
- Kibana / Agent Builder: `KIBANA_URL`, `KIBANA_API_KEY`, `ELASTIC_AGENT_ID`
- EIS model IDs: `INFERENCE_ENDPOINT_ID`, `RERANKER_ENDPOINT_ID`, `JINA_EMBEDDING_MODEL`, `JINA_RERANKER_MODEL`
- Paths: `DATA_DIR`, `PROJECT_ROOT`

**Important:** Never call `os.getenv()` directly in server files — always import from `config.py`.

### Data Files

```
data/
├── ferry_terminals.json   # Static terminal locations (rarely changes)
└── sample_events.json     # Synthetic demo events, March–June 2026
```

Ferry schedules are **not stored in a file** — `wsdot_server.py` calls the WSDOT Ferries API live on every request.

### MCP Server Structure

**`wsdot_server.py`** exposes:
- **1 Resource**: `get_terminals()` — static terminal list from `ferry_terminals.json`
- **7 Tools**: `find_nearest_terminals`, `get_ferry_schedule`, `get_todays_sailings`, `get_ferry_fare`, `get_drive_time`, `estimate_total_travel`, `generate_expense_estimate`
- **2 Prompts**: `user_preferences`, `plan_trip`

**`events_write_server.py`** exposes:
- **2 Tools**: `create_event`, `save_travel_plan`

**`events_read_server.py`** exposes:
- **1 Tool**: `search_events` — forwards natural language to Elastic Agent Builder converse API

### Elasticsearch

The events index uses **`semantic_text`** for zero-config embeddings:
- `description` has `copy_to: description_vector`
- `description_vector` is `semantic_text` with `inference_id: jina-embeddings-v5`
- EIS (Elastic Inference Service) handles embedding generation on ingest — no pipeline needed

Kibana Agent Builder has 4 ES|QL tools: `search_upcoming_events`, `search_events_by_topic`, `search_events_by_date_range`, `get_my_presentations`.

## Development Commands

```bash
# Install dependencies
pip install elasticsearch fastmcp pydantic python-dotenv requests httpx

# Set up environment
cp .env.example .env
# Edit .env with your API keys

# Initialize Elasticsearch (first time only)
python setup/elasticsearch_setup.py --all

# Run a server directly for testing
python wsdot_server.py
```

### Claude Desktop Integration

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

## Key Implementation Details

### The `_helper` Pattern (FastMCP Gotcha)

`@mcp.tool()` replaces the decorated function with a `FunctionTool` object — not directly callable from Python. Any tool that needs to be called from other Python code must have a private `_helper` function:

```python
def _get_ferry_fare(trip_date, dep, arr, mode):   # contains logic
    ...

@mcp.tool(name="get_ferry_fare")
def get_ferry_fare(trip_date, dep, arr, mode):    # thin wrapper
    return _get_ferry_fare(trip_date, dep, arr, mode)

# Other functions call the helper, never the tool
def _generate_expense_estimate(...):
    fare = _get_ferry_fare(...)                    # ✓ correct
```

### Terminal Names

`ferry_terminals.json` has two name fields:
- `name` — simple name used for API lookups (`"Bremerton"`, `"Bainbridge Island"`)
- `display_name` — human-readable (`"Bremerton (Downtown)"`)

`_find_nearest_terminals` returns `name` (not `display_name`) so that `TERMINAL_PAIRS` and `TERMINAL_IDS` lookups work correctly.

### Terminal Pairs

`TERMINAL_PAIRS` in `wsdot_server.py` maps each Kitsap-side terminal to its correct mainland counterpart. This replaces any destination-guessing logic:

```python
TERMINAL_PAIRS = {
    "southworth":        "fauntleroy",   # West Seattle, NOT downtown
    "bainbridge island": "seattle",
    "bremerton":         "seattle",
    "kingston":          "edmonds",
    "tahlequah":         "point defiance",
}
```

### Cost Calculations

**Mileage**: `$0.70/mile` (IRS standard rate), Google Maps distance in meters × `0.000621371`

**Ferry fares**: Live WSDOT Fares API. Eastbound (to mainland) = paid, westbound (to islands) = free.

**Crossing times**: Hardcoded in `CROSSING_TIMES` (frozenset keys) — the WSDOT schedule API does not return a crossing time field.

### Travel Plans

`generate_expense_estimate` returns a `travel_plan` dict. `save_travel_plan` embeds it directly in the event document (no separate index). The `choice` sub-object records the route actually taken:

```python
travel_plan = {
    "origin": ..., "destination": ..., "trip_date": ...,
    "recommended_route": ...,
    "choice": {"route": ..., "total_cost": ...},  # optional, set at save time
    "routes": [...]
}
```

### Elastic Agent Builder

`events_read_server.py` wraps `ElasticAgentClient.chat()` from `elastic_agent_example.py`. The client POSTs to `{KIBANA_URL}/api/agent_builder/converse` with `{input, agent_id, conversation_id}`. ES|QL tools are registered in Kibana separately via `setup/elasticsearch_setup.py --create-tools`.

## Common Pitfalls

1. **`FunctionTool` not callable**: Use the `_helper` pattern — see above.

2. **Terminal name mismatch**: Always use the `name` field (not `display_name`) from terminal data for TERMINAL_PAIRS/TERMINAL_IDS lookups.

3. **Southworth → Fauntleroy**: Southworth goes to Fauntleroy (West Seattle), not downtown Seattle. The `user_preferences` prompt reminds the LLM of this, and `TERMINAL_PAIRS` enforces it in code.

4. **WSDOT schedule response structure**: Times are at `data["TerminalCombos"][0]["Times"]`, not `data["Times"]`. Times use `/Date(milliseconds+offset)/` format.

5. **Import order**: Always import from `config.py`. Never use `os.getenv()` directly in server files.

6. **Elasticsearch must be reachable**: Servers will fail at startup if ES is unreachable (for write/read servers).

## API Keys Required

- `WSDOT_API_KEY` — Washington State DOT ferry API
- `GOOGLE_MAPS_API_KEY` — Geocoding and Directions APIs
- `ELASTIC_API_KEY` — Elastic Cloud Serverless
- `KIBANA_API_KEY` — Kibana Agent Builder access
- `ELASTIC_AGENT_ID` — ID of the Agent Builder agent with ES|QL tools

All keys go in `.env` (never commit this file).
