"""
MCP server for writing events to Elasticsearch.

Intentionally minimal — just create_event. Reading is handled by the
Elastic Agent Builder (events_read_server.py).
"""

import logging
from typing import Optional

from fastmcp import FastMCP
from elasticsearch import Elasticsearch
import datetime
from config import ELASTIC_ENDPOINT, ELASTIC_API_KEY, EVENT_INDEX

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

es = Elasticsearch(hosts=ELASTIC_ENDPOINT, api_key=ELASTIC_API_KEY)
mcp = FastMCP("events-write")


@mcp.tool(
    name="create_event",
    description=(
        "Add a new event to the events index. The description is automatically embedded "
        "using jina-embeddings-v5 so it becomes searchable semantically right away."
    ),
)
def create_event(
    title: str,
    description: str,
    location: str,
    start_time: str,
    end_time: str,
    url: Optional[str] = None,
    presenting: bool = False,
    talk_title: Optional[str] = None,
) -> dict:
    """
    Create a new event in Elasticsearch.

    Args:
        title: Event name.
        description: Full description — this drives semantic search.
        location: City, venue, or 'Remote'.
        start_time: ISO 8601 with timezone (e.g. '2026-04-10T18:00:00-07:00').
        end_time: ISO 8601 with timezone.
        url: Link to event page.
        presenting: True if you are speaking at this event.
        talk_title: Title of your talk (if presenting).

    Returns:
        {"event_id": str, "event": dict}
    """
    doc = {
        "title": title,
        "description": description,
        "description_vector": description,  # copy_to handled by index mapping
        "location": location,
        "start_time": start_time,
        "end_time": end_time,
        "url": url,
        "presenting": presenting,
        "talk_title": talk_title,
        "created_at": datetime.datetime.now().isoformat(),
    }
    resp = es.index(index=EVENT_INDEX, document=doc)
    logger.info(f"Created event '{title}' with id {resp['_id']}")
    return {"event_id": resp["_id"], "event": doc}


@mcp.tool(
    name="save_travel_plan",
    description=(
        "Save a travel plan to an existing event. Pass the travel_plan object from "
        "generate_expense_estimate. Optionally record the chosen route with chosen_route "
        "and chosen_total_cost to document which option was actually taken."
    ),
)
def save_travel_plan(
    event_id: str,
    travel_plan: dict,
    chosen_route: Optional[str] = None,
    chosen_total_cost: Optional[float] = None,
) -> dict:
    """
    Partially updates an event document with a travel plan.

    Args:
        event_id: The Elasticsearch document ID of the event.
        travel_plan: The travel_plan dict returned by generate_expense_estimate.
        chosen_route: Description of the route you're actually taking
                      (e.g. 'Southworth → Fauntleroy ferry').
        chosen_total_cost: Total cost of the chosen route in dollars.

    Returns:
        {"event_id": str, "result": str}
    """
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
    logger.info(f"Saved travel plan to event {event_id} (result: {resp['result']})")
    return {"event_id": event_id, "result": resp["result"]}


if __name__ == "__main__":
    mcp.run()
