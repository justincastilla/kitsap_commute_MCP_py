# Slide Updates & Additions

This document captures corrections, updated code samples, and new sections to add to the
presentation. Add these as new/replacement slides alongside the existing deck.

---

## CORRECTION — Title / Subtitle

**Old:** "by ferry or I5?"
**New:** "by ferry or freeway?"

The project now covers multiple mainland routes beyond I-5 (Fauntleroy via WA-16, Edmonds
via WA-104, etc.), so "freeway" is more accurate.

---

## UPDATE — How I Built This: Architecture (Step 3 slide)

The function list on this slide is from the original single-server design. The project now
splits into **three FastMCP servers**, each with a focused role.

**Old function list:**
```
fetch_ferry_schedules()  fetch_terminals()
find_nearby_terminals()  drive_time()
get_ferry_times()        ferry_cost()
search_events()          create_event()
```

**New — three servers:**

| Server | Tools |
|---|---|
| `wsdot_server.py` | `find_nearest_terminals`, `get_ferry_schedule`, `get_todays_sailings`, `get_ferry_fare`, `get_drive_time`, `estimate_total_travel`, `generate_expense_estimate` |
| `events_write_server.py` | `create_event`, `save_travel_plan` |
| `events_read_server.py` | `search_events` (Elastic Agent Builder wrapper) |

**Why split?**
- **Separation of concerns**: ferry data, event writes, and AI-powered search are independent
- **Security**: the read path (Agent Builder) and write path (direct Elasticsearch) have different
  auth requirements
- **Demo clarity**: each server tells a clear story on its own

---

## UPDATE — Stack Slide (remove Docker)

Remove "Docker — Everything contained in its own environment."

Docker was removed from the project. The three MCP servers run as direct `stdio` processes
launched by Claude Desktop. Elasticsearch runs on **Elastic Serverless** (cloud).

Updated stack:

| Component | Role |
|---|---|
| **Python + FastMCP 2.x** | MCP server framework |
| **Elastic Serverless** | Event storage, semantic search, ML inference |
| **Elastic Agent Builder** | Kibana-based AI agent with ES\|QL tool execution |
| **WSDOT Ferries API** | Live ferry schedules and fares |
| **Google Maps API** | Drive times, geocoding, mileage |

---

## UPDATE — Resources Slide (replace entirely)

The original slide showed a resource that fetched terminal data from a JSON file. The
resource and the file are both gone — replaced by a `TERMINAL_LOCATIONS` dict hardcoded
directly in `wsdot_server.py` alongside the other terminal constants.

**Why remove the resource?**
MCP resources are only useful if a client explicitly requests them. In practice, Claude
Desktop never reads this resource — the LLM calls `find_nearest_terminals` (a tool) instead.
The resource was providing no value.

**Why remove the JSON file?**
The WSDOT API doesn't return coordinates, so we'd still need to store lat/lng somewhere.
Rather than maintaining a separate file, the coordinates live inline with the other
terminal data the server already hardcodes:

```python
# wsdot_server.py — all terminal data in one place

TERMINAL_IDS: dict[str, int] = {
    "seattle": 7, "bainbridge island": 3, "southworth": 20,
    "fauntleroy": 9, "edmonds": 8, "kingston": 12,
    "bremerton": 4, "point defiance": 16, "tahlequah": 21,
    ...
}

TERMINAL_LOCATIONS: dict[str, tuple[float, float]] = {
    "Bremerton":         (47.56212, -122.62392),
    "Southworth":        (47.51204, -122.49749),
    "Bainbridge Island": (47.62309, -122.51081),
    "Seattle":           (47.60270, -122.33852),
    "Fauntleroy":        (47.52320, -122.39548),
    "Kingston":          (47.79630, -122.49645),
    "Edmonds":           (47.81044, -122.38296),
    ...
}

TERMINAL_PAIRS: dict[str, str] = {
    "southworth":        "fauntleroy",
    "bainbridge island": "seattle",
    "bremerton":         "seattle",
    ...
}
```

`_find_nearest_terminals` iterates `TERMINAL_LOCATIONS` directly — no file I/O, no
try/except, no extra fields to parse:

```python
def _find_nearest_terminals(address: str, max_results: int = 3) -> dict:
    # geocode the user's origin via Google Maps
    ...
    addr_lat, addr_lng = loc["lat"], loc["lng"]

    terminals = []
    for name, (lat, lng) in TERMINAL_LOCATIONS.items():
        dist = haversine(addr_lat, addr_lng, lat, lng)
        terminals.append({"name": name, "lat": lat, "lng": lng, "distance_km": round(dist, 2)})

    terminals.sort(key=lambda x: x["distance_km"])
    return {"terminals": terminals[:max_results]}
```

---

## REPLACEMENT — Resources Code Sample Slide

> Replace the terminal JSON resource example with this.

### What are Resources actually for?

Resources are the **read-only data layer** of MCP. Think of them as the difference between
a file you can open and read vs. a button you can press:

| | Resources | Tools |
|---|---|---|
| Analogy | File / document | Function call |
| Direction | Server → Client | Client → Server → Client |
| Triggered by | Client requests it | LLM decides to call it |
| Side effects | None | Yes (API calls, DB writes, etc.) |
| Good for | Reference data, config, schemas | Actions, lookups, computations |

### Why Claude Desktop barely uses them

Claude Desktop is **LLM-driven** — the model decides what to do next. It reaches for tools
because tools give it something to act on. Resources require the *client* to proactively
fetch and surface them. Claude Desktop will read a resource if you explicitly ask
("show me the available ferry terminals"), but it won't browse them on its own.

Resources shine in **purpose-built MCP clients** — apps where a human or system wants
to browse available data directly:

---

### Example 1: An IDE plugin

A coding assistant MCP server exposes project files as resources. The IDE sidebar
can list and display them without involving the LLM at all.

```python
@mcp.resource("file://{path}")
def read_project_file(path: str) -> str:
    return open(path).read()
```

The IDE fetches `file://src/main.py` directly and shows it in the editor.
The LLM only gets involved when the user asks a question about it.

---

### Example 2: A documentation browser

A docs server exposes API reference pages. A custom client renders them
as navigable pages — no LLM round-trip needed to display content.

```python
@mcp.resource("docs://api/{endpoint}")
def get_endpoint_docs(endpoint: str) -> str:
    return DOCS[endpoint]
```

---

### Example 3: A live config a human needs to inspect

A deployment server exposes current environment config. A dashboard
client displays it. The LLM can also read it when reasoning about a problem.

```python
@mcp.resource(
    uri="config://environment",
    name="Current Environment",
    description="Active deployment config — region, feature flags, rate limits.",
)
def get_environment_config() -> dict:
    return {
        "region": os.getenv("AWS_REGION"),
        "feature_flags": load_flags(),
        "rate_limit_rpm": 1000,
    }
```

---

### The rule of thumb

> **Use a resource when the data is worth reading on its own.**
> Use a tool when the value comes from *doing something* with it.

Ferry terminal coordinates? Worth nothing to a human browsing a sidebar.
The drive time *from* those terminals? That's a tool.

---

## UPDATE — Tools Slide (corrected `create_event`)

The original slide had several bugs in the code sample. Here is the corrected version:

**Old (buggy):**
```python
@mcp.tool(
    name="create_event",
    description="Create a new event in Elasticsearch."
)
def create_event(eventDoc) -> dict:
    resp = es.index(index="events", document=event_doc)
    return {"event_id": resp["id"], "event": resp["_source"}   # ← 3 bugs
```

**New (correct, with full typed signature):**
```python
# events_write_server.py

from typing import Optional
from fastmcp import FastMCP
from elasticsearch import Elasticsearch
from config import ELASTIC_ENDPOINT, ELASTIC_API_KEY, EVENT_INDEX

es = Elasticsearch(hosts=ELASTIC_ENDPOINT, api_key=ELASTIC_API_KEY)
mcp = FastMCP("events-write")

@mcp.tool(
    name="create_event",
    description=(
        "Add a new event to the events index. The description is automatically "
        "embedded using jina-embeddings-v5 so it becomes searchable semantically."
    ),
)
def create_event(
    title: str,
    description: str,
    location: str,
    topic: str,
    start_time: str,
    end_time: str,
    url: Optional[str] = None,
    presenting: bool = False,
    talk_title: Optional[str] = None,
) -> dict:
    doc = {
        "title": title,
        "description": description,
        "location": location,
        "topic": topic,
        "start_time": start_time,
        "end_time": end_time,
        "url": url,
        "presenting": presenting,
        "talk_title": talk_title,
    }
    resp = es.index(index=EVENT_INDEX, document=doc)
    return {"event_id": resp["_id"], "event": doc}
```

The typed signature is the schema. FastMCP + Pydantic reads the type hints and generates
the JSON schema the LLM uses to call the tool correctly — no extra work needed.

---

## NEW SECTION — The `_helper` Pattern (Important FastMCP Gotcha)

> Add this as a slide between the Tools and Prompts slides.

**The problem:** FastMCP's `@mcp.tool()` replaces your function with a `FunctionTool` object.
That object is not directly callable from Python:

```python
@mcp.tool(name="get_ferry_fare")
def get_ferry_fare(trip_date, departing_terminal, arriving_terminal):
    ...

# Later, in generate_expense_estimate:
fare = get_ferry_fare(...)    # ← TypeError: 'FunctionTool' object is not callable
```

**The solution — extract to a private `_helper` function:**

```python
# Private helper contains the actual logic
def _get_ferry_fare(trip_date, departing_terminal, arriving_terminal, travel_mode="drive"):
    ...
    return {"fare_amount": fare_amount, "cost_summary": cost_summary}

# Tool is a thin wrapper — just calls the helper
@mcp.tool(name="get_ferry_fare", description="Return ferry fare for a route.")
def get_ferry_fare(trip_date, departing_terminal, arriving_terminal, travel_mode="drive"):
    return _get_ferry_fare(trip_date, departing_terminal, arriving_terminal, travel_mode)

# Other tools call the helper directly, not the tool
def _generate_expense_estimate(origin, destination, trip_date, travel_mode="drive"):
    fare = _get_ferry_fare(trip_date, dep_terminal, arr_terminal, travel_mode)
    ...
```

Rule of thumb: **every tool that might be called from other Python code gets a `_` helper.**

---

## NEW SECTION — Elasticsearch + Elastic Agent Builder

> Add this as a new section after the existing Elasticsearch slide.

### Elasticsearch now: Elastic Inference Service + Jina

The events index uses **`semantic_text`** — a field type that automatically handles
embedding generation via Elastic Inference Service (EIS). No pipeline to manage,
no separate embedding step.

```python
# setup/elasticsearch_setup.py

# 1. Create the EIS inference endpoint (jina-embeddings-v5-text-small)
es.inference.put(
    task_type="text_embedding",
    inference_id="jina-embeddings-v5",
    body={
        "service": "elastic",
        "service_settings": {"model_id": "jina-embeddings-v5-text-small"},
    },
)

# 2. Index mapping: description copies to description_vector, which auto-embeds
mapping = {
    "mappings": {
        "properties": {
            "description": {
                "type": "text",
                "copy_to": "description_vector",      # ← copies on ingest
            },
            "description_vector": {
                "type": "semantic_text",
                "inference_id": "jina-embeddings-v5", # ← EIS handles embeddings
            },
        }
    }
}
es.indices.create(index="events", body=mapping)
```

When a document is indexed, Elasticsearch automatically calls EIS to embed
`description_vector`. No client-side embedding code needed.

---

### Elastic Agent Builder: AI-Powered Event Search

Instead of writing our own semantic search query, we hand the question to an
**Elastic Agent Builder** agent that has custom ES|QL tools attached to it.

```python
# events_read_server.py

import httpx
from fastmcp import FastMCP
from config import KIBANA_URL, KIBANA_API_KEY, ELASTIC_AGENT_ID

mcp = FastMCP("events-read")

@mcp.tool(
    name="search_events",
    description="Search events using the Elastic Agent Builder. Ask naturally.",
)
def search_events(query: str, conversation_id: str = "") -> dict:
    """
    Args:
        query: Natural language question (e.g. 'any ML events next month?').
        conversation_id: Pass the previous response's conversation_id to continue
                         a multi-turn conversation with the agent.
    """
    headers = {
        "kbn-xsrf": "true",
        "Authorization": f"ApiKey {KIBANA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": query,
        "agent_id": ELASTIC_AGENT_ID,
        **({"conversation_id": conversation_id} if conversation_id else {}),
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{KIBANA_URL}/api/agent_builder/converse",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "response": data.get("output", ""),
        "conversation_id": data.get("conversation_id", ""),
    }
```

The Agent Builder agent has **ES|QL tools** registered in Kibana that it can call:

```
search_upcoming_events  →  FROM events | WHERE start_time >= NOW() | SORT start_time ASC
search_events_by_topic  →  FROM events | WHERE MATCH(title, ?keyword) ...
search_events_by_date_range  →  FROM events | WHERE start_time BETWEEN ?start AND ?end
get_my_presentations    →  FROM events | WHERE presenting == true
```

The LLM running inside Agent Builder decides which ES|QL tool to call, executes it,
and returns a natural language answer. Our MCP tool just forwards the question and
returns the response.

---

## NEW SECTION — Expense Tracking (Travel Plans in Events)

> This is the new section that closes the loop between ferry planning and the calendar.

### The Problem

After estimating travel costs, where does that information go? Previously: nowhere.
Each conversation started fresh. The expense estimate was computed and discarded.

### The Solution: Embed `travel_plan` in the Event Document

```
Event document
├── title, description, location, topic
├── start_time, end_time, url
├── presenting, talk_title
└── travel_plan  ← new embedded object
    ├── origin
    ├── calculated_at
    ├── recommended_route
    ├── choice          ← what route you actually took
    │   ├── route
    │   └── total_cost
    └── routes[]        ← all computed options
        ├── type (ferry / drive)
        ├── departure_terminal, arrival_terminal
        ├── drive_to_terminal_minutes
        ├── crossing_time_minutes
        ├── drive_from_terminal_minutes
        ├── total_minutes
        ├── ferry_fare
        ├── mileage_cost
        └── total_cost
```

No separate index. The plan lives with the event it belongs to.

---

### `generate_expense_estimate` — computing all route options

```python
# wsdot_server.py

# Maps each Kitsap terminal to its correct mainland counterpart
TERMINAL_PAIRS: dict[str, str] = {
    "southworth":      "fauntleroy",   # Southworth → West Seattle (NOT downtown)
    "bainbridge island": "seattle",
    "bremerton":       "seattle",
    "kingston":        "edmonds",
    "tahlequah":       "point defiance",
}

def _generate_expense_estimate(
    origin: str,
    destination: str,
    trip_date: str,
    travel_mode: str = "drive",
) -> dict:
    routes = []

    # --- Ferry options ---
    nearby = _find_nearest_terminals(origin, max_results=3).get("terminals", [])

    for terminal in nearby:
        dep_terminal = terminal["name"]

        # Correct arrival terminal per departure — no destination-guessing
        arr_terminal = TERMINAL_PAIRS.get(dep_terminal.lower().strip())
        if arr_terminal is None:
            continue
        arr_terminal = arr_terminal.title()

        schedule = _get_ferry_schedule(trip_date, dep_terminal, arr_terminal)
        if schedule.get("error") or not schedule.get("sailings"):
            continue

        drive_to   = _get_drive_time(origin, f"{dep_terminal} Ferry Terminal, WA")
        drive_from = _get_drive_time(f"{arr_terminal} Ferry Terminal, WA", destination)
        fare       = _get_ferry_fare(trip_date, dep_terminal, arr_terminal, travel_mode)

        ferry_fare   = fare.get("fare_amount", 0)
        mileage_cost = round(drive_to["mileage_cost"] + drive_from["mileage_cost"], 2)

        routes.append({
            "type": "ferry",
            "departure_terminal": dep_terminal,
            "arrival_terminal": arr_terminal,
            "drive_to_terminal_minutes":   drive_to["drive_minutes"],
            "crossing_time_minutes":       schedule.get("crossing_time_minutes", 0),
            "drive_from_terminal_minutes": drive_from["drive_minutes"],
            "total_minutes": (
                drive_to["drive_minutes"]
                + schedule.get("crossing_time_minutes", 0)
                + drive_from["drive_minutes"]
            ),
            "ferry_fare":    ferry_fare,
            "mileage_cost":  mileage_cost,
            "total_cost":    round(ferry_fare + mileage_cost, 2),
        })

    # --- Drive only ---
    drive_only = _get_drive_time(origin, destination)
    routes.append({
        "type": "drive",
        "total_minutes": drive_only["drive_minutes"],
        "mileage_cost":  drive_only["mileage_cost"],
        "total_cost":    drive_only["mileage_cost"],
    })

    recommended = min(routes, key=lambda r: r["total_cost"])
    rec_label = (
        f"{recommended['departure_terminal']} → {recommended['arrival_terminal']} ferry"
        if recommended["type"] == "ferry"
        else "Drive only"
    )

    return {
        "origin": origin,
        "destination": destination,
        "trip_date": trip_date,
        "calculated_at": datetime.now().astimezone().isoformat(),
        "recommended_route": rec_label,
        "routes": routes,
    }

@mcp.tool(
    name="generate_expense_estimate",
    description=(
        "Compute a full expense estimate for a trip: ferry fare + mileage for each "
        "route option. Returns a travel_plan object ready to save to an event."
    ),
)
def generate_expense_estimate(
    origin: str, destination: str, trip_date: str, travel_mode: str = "drive"
) -> dict:
    return _generate_expense_estimate(origin, destination, trip_date, travel_mode)
```

**Sample output** (Port Orchard → Amazon Meeting Center, Seattle):

```
Routes found: 4
Recommended: Bremerton → Seattle ferry

ferry: Bremerton → Seattle     | 85 min | fare=$19.70  mileage=$7.17  total=$26.87 ✓
ferry: Southworth → Fauntleroy | 69 min | fare=$15.40  mileage=$12.78 total=$28.18
ferry: Bainbridge Is → Seattle | 93 min | fare=$19.70  mileage=$25.76 total=$45.46
drive: only                    | 67 min | fare=$0      mileage=$42.55 total=$42.55
```

---

### `save_travel_plan` — writing the plan back to the event

```python
# events_write_server.py

@mcp.tool(
    name="save_travel_plan",
    description=(
        "Save a travel plan to an existing event. Pass the travel_plan object from "
        "generate_expense_estimate. Optionally record the chosen route."
    ),
)
def save_travel_plan(
    event_id: str,
    travel_plan: dict,
    chosen_route: Optional[str] = None,
    chosen_total_cost: Optional[float] = None,
) -> dict:
    plan = {**travel_plan}

    if chosen_route is not None and chosen_total_cost is not None:
        plan["choice"] = {
            "route": chosen_route,
            "total_cost": chosen_total_cost,
        }

    resp = es.update(
        index=EVENT_INDEX,
        id=event_id,
        doc={"travel_plan": plan},
    )
    return {"event_id": event_id, "result": resp["result"]}
```

### The complete workflow (LLM conversation)

```
User:  "Plan my trip to the Seattle AI Agents Meetup on March 19th."

LLM:   search_events("Seattle AI Agents Meetup")
       → event_id: "abc123", location: "2121 7th Ave Seattle", start_time: "2026-03-19T18:00"

       generate_expense_estimate(
           origin="Port Orchard, WA",
           destination="2121 7th Ave, Seattle, WA",
           trip_date="2026-03-19"
       )
       → Bremerton→Seattle: $26.87 (recommended)
         Southworth→Fauntleroy: $28.18
         Drive only: $42.55

LLM:   "Recommended: Bremerton ferry at $26.87 total.
        Want me to save this plan to the event?"

User:  "Yes, I'll take the Bremerton ferry."

LLM:   save_travel_plan(
           event_id="abc123",
           travel_plan={...},
           chosen_route="Bremerton → Seattle ferry",
           chosen_total_cost=26.87
       )
       → saved ✓
```

---

## UPDATE — Prompts Slide (updated example)

Replace the `get_there_with_a_buffer` example with the current prompt from `wsdot_server.py`:

```python
# wsdot_server.py

@mcp.prompt("plan_trip")
def plan_trip(origin: str = None, destination: str = None, event_time: str = None):
    """Guide the AI through planning a Kitsap commute."""
    parts = ["Review user_preferences before planning.\n"]
    parts.append(f"Origin: {origin}"           if origin      else "Ask for the origin.")
    parts.append(f"Destination: {destination}" if destination else "Ask for the destination.")
    parts.append(f"Event time: {event_time}"   if event_time  else "Ask for the event time.")
    parts.append("""
Steps:
1. Call estimate_total_travel(origin, destination, event_time) for a complete breakdown.
2. For each viable ferry option, call get_ferry_fare to add cost information.
3. Present results as a table:
   Route | Leave | Drive to Terminal | Ferry Departs | Crossing | Drive to Event | Arrive | Cost
4. Always include one driving-only row.
    """)
    return "\n".join(parts)

@mcp.prompt("user_preferences")
def user_preferences():
    return """
    User Preferences:
    - Always provide exactly 3 route options
    - One option MUST be driving-only (no ferry)
    - Target arrival: at least 15 minutes before the event
    - The Southworth ferry goes to Fauntleroy (West Seattle), NOT downtown Seattle
    """
```

The key addition: `user_preferences` now explicitly states the **Southworth → Fauntleroy**
rule. This matters because Fauntleroy is in West Seattle — the LLM needs to know to add
drive time from Fauntleroy to downtown destinations.

---

## UPDATE — Further Work Slide

Remove items that are now implemented. Add new ones.

**Now implemented (remove from "further work"):**
- ~~Store my chosen selections and prioritize them if they worked out well~~ → `save_travel_plan` with `choice` field

**Still to do (keep/update):**
- **Notifications** — abstract mentions "sends timely notifications for events" — not yet built
  - Idea: when `save_travel_plan` is called, schedule a reminder based on `drive_to_terminal_minutes`
- Passenger-only ferry integration (walk-on fare via `travel_mode="walk"`)
- Check for service disruptions via WSDOT Alerts API
- Multi-agent version: orchestrator agent delegates to wsdot-ferry and events agents

---

## CODE REPO

Update GitHub link on final slide:

```
https://github.com/justincastilla/kitsap-commute-helper
```
