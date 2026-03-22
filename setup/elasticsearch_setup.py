"""
Elasticsearch + Kibana Agent Builder setup for Kitsap Commute MCP.

Steps (run with --all or individually):
  1. Create EIS inference endpoint  (jina-embeddings-v5-text-small)
  2. Create EIS reranker endpoint   (jina-reranker-v3)
  3. Create events index            (semantic_text mapping)
  4. Load sample data               (data/sample_events.json)
  5. Create Agent Builder ES|QL tools in Kibana

Usage:
    python setup/elasticsearch_setup.py --all
    python setup/elasticsearch_setup.py --create-index
    python setup/elasticsearch_setup.py --create-tools
"""

import sys
import json
import logging
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from config import (
    ELASTIC_ENDPOINT,
    ELASTIC_API_KEY,
    EVENT_INDEX,
    DATA_DIR,
    KIBANA_URL,
    KIBANA_API_KEY,
    ELASTIC_AGENT_ID,
    INFERENCE_ENDPOINT_ID,
    RERANKER_ENDPOINT_ID,
    JINA_EMBEDDING_MODEL,
    JINA_RERANKER_MODEL,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

es = Elasticsearch(hosts=ELASTIC_ENDPOINT, api_key=ELASTIC_API_KEY)

# ---------------------------------------------------------------------------
# Elasticsearch Inference Endpoints (EIS)
# ---------------------------------------------------------------------------

def create_inference_endpoint():
    """Create EIS inference endpoint for jina-embeddings-v5-text-small."""
    logger.info(f"Creating inference endpoint: {INFERENCE_ENDPOINT_ID}")
    body = {
        "service": "elastic",
        "service_settings": {"model_id": JINA_EMBEDDING_MODEL},
    }
    try:
        es.inference.put(
            task_type="text_embedding",
            inference_id=INFERENCE_ENDPOINT_ID,
            body=body,
        )
        logger.info(f"✓ Inference endpoint '{INFERENCE_ENDPOINT_ID}' created.")
    except Exception as e:
        if "already exists" in str(e).lower() or "resource_already_exists" in str(e).lower():
            logger.info(f"  Endpoint '{INFERENCE_ENDPOINT_ID}' already exists, skipping.")
        else:
            raise


def create_reranker_endpoint():
    """Create EIS reranker endpoint for jina-reranker-v3."""
    logger.info(f"Creating reranker endpoint: {RERANKER_ENDPOINT_ID}")
    body = {
        "service": "elastic",
        "service_settings": {"model_id": JINA_RERANKER_MODEL},
    }
    try:
        es.inference.put(
            task_type="rerank",
            inference_id=RERANKER_ENDPOINT_ID,
            body=body,
        )
        logger.info(f"✓ Reranker endpoint '{RERANKER_ENDPOINT_ID}' created.")
    except Exception as e:
        if "already exists" in str(e).lower() or "resource_already_exists" in str(e).lower():
            logger.info(f"  Endpoint '{RERANKER_ENDPOINT_ID}' already exists, skipping.")
        else:
            raise


# ---------------------------------------------------------------------------
# Events Index
# ---------------------------------------------------------------------------

def create_event_index():
    """Create the events index with semantic_text mapping for jina embeddings."""
    logger.info(f"Creating index: {EVENT_INDEX}")
    mapping = {
        "mappings": {
            "properties": {
                "title": {"type": "text"},
                "description": {
                    "type": "text",
                    "copy_to": "description_vector",
                },
                "description_vector": {
                    "type": "semantic_text",
                    "inference_id": INFERENCE_ENDPOINT_ID,
                },
                "location": {"type": "text"},
                "topic": {"type": "keyword"},
                "start_time": {"type": "date"},
                "end_time": {"type": "date"},
                "url": {"type": "keyword"},
                "presenting": {"type": "boolean"},
                "talk_title": {"type": "text"},
                "travel_plan": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "keyword"},
                        "calculated_at": {"type": "date"},
                        "recommended_route": {"type": "keyword"},
                        "choice": {
                            "type": "object",
                            "properties": {
                                "route": {"type": "keyword"},
                                "total_cost": {"type": "float"},
                            },
                        },
                        "routes": {
                            "type": "nested",
                            "properties": {
                                "type": {"type": "keyword"},
                                "departure_terminal": {"type": "keyword"},
                                "arrival_terminal": {"type": "keyword"},
                                "drive_to_terminal_minutes": {"type": "integer"},
                                "crossing_time_minutes": {"type": "integer"},
                                "drive_from_terminal_minutes": {"type": "integer"},
                                "total_minutes": {"type": "integer"},
                                "ferry_fare": {"type": "float"},
                                "mileage_cost": {"type": "float"},
                                "total_cost": {"type": "float"},
                            },
                        },
                    },
                },
            }
        }
    }
    try:
        if es.indices.exists(index=EVENT_INDEX):
            es.indices.delete(index=EVENT_INDEX)
            logger.info(f"  Deleted existing index '{EVENT_INDEX}'.")
        es.indices.create(index=EVENT_INDEX, body=mapping)
        logger.info(f"✓ Index '{EVENT_INDEX}' created.")
    except Exception as e:
        logger.error(f"Error creating index: {e}")
        raise


def load_sample_events():
    """Bulk index sample events from data/sample_events.json."""
    path = DATA_DIR / "sample_events.json"
    with open(path) as f:
        events = json.load(f)

    actions = [{"_index": EVENT_INDEX, "_source": e} for e in events]
    success, failed = bulk(es, actions, stats_only=True)
    logger.info(f"✓ Indexed {success} events ({failed} failed).")


# ---------------------------------------------------------------------------
# Kibana Agent Builder — ES|QL Tools
# ---------------------------------------------------------------------------

# These tools are registered with the Elastic Agent Builder so the agent
# can query the events index when you call events_read_server's search_events.
ESQL_TOOLS = [
    {
        "id": "search_upcoming_events",
        "description": (
            "Find events happening from now onwards. "
            "Use this for questions like 'what events are coming up?' or 'what's on next month?'."
        ),
        "type": "esql",
        "configuration": {
            "query": (
                "FROM {index} "
                "| WHERE start_time >= NOW() "
                "| SORT start_time ASC "
                "| LIMIT 10 "
                "| KEEP title, description, location, topic, start_time, end_time, url, presenting, talk_title"
            ).format(index=EVENT_INDEX),
            "params": {},
        },
    },
    {
        "id": "search_events_by_topic",
        "description": (
            "Search events by topic or keyword in the title. "
            "Use for questions like 'any machine learning events?' or 'find elasticsearch talks'."
        ),
        "type": "esql",
        "configuration": {
            "query": (
                "FROM {index} "
                "| WHERE MATCH(title, ?keyword) OR MATCH(description, ?keyword) "
                "| WHERE start_time >= NOW() "
                "| SORT start_time ASC "
                "| LIMIT 10 "
                "| KEEP title, description, location, topic, start_time, end_time, url, presenting"
            ).format(index=EVENT_INDEX),
            "params": {
                "keyword": {"type": "string", "description": "Topic or keyword to search for"},
            },
        },
    },
    {
        "id": "search_events_by_date_range",
        "description": (
            "Find events within a specific date range. "
            "Use for questions like 'what's happening in April?' or 'events between March and May'."
        ),
        "type": "esql",
        "configuration": {
            "query": (
                "FROM {index} "
                "| WHERE start_time >= ?start_date AND start_time <= ?end_date "
                "| SORT start_time ASC "
                "| LIMIT 20 "
                "| KEEP title, description, location, topic, start_time, end_time, url, presenting, talk_title"
            ).format(index=EVENT_INDEX),
            "params": {
                "start_date": {"type": "date", "description": "Start of range (ISO 8601)"},
                "end_date": {"type": "date", "description": "End of range (ISO 8601)"},
            },
        },
    },
    {
        "id": "get_my_presentations",
        "description": (
            "List events where I am presenting or speaking. "
            "Use for 'where am I speaking?' or 'what talks do I have scheduled?'."
        ),
        "type": "esql",
        "configuration": {
            "query": (
                "FROM {index} "
                "| WHERE presenting == true "
                "| SORT start_time ASC "
                "| KEEP title, talk_title, location, topic, start_time, end_time, url"
            ).format(index=EVENT_INDEX),
            "params": {},
        },
    },
]


def create_agent_tools():
    """
    Create ES|QL tools in Kibana Agent Builder via API.

    Note: The Agent Builder tools API may require configuration in Kibana UI
    if the programmatic API is not yet available on your deployment.
    This script attempts creation and prints the tool definitions on failure.
    """
    if not KIBANA_URL:
        logger.warning("KIBANA_URL not set — skipping tool creation. Configure tools manually in Kibana.")
        _print_tools()
        return

    if not ELASTIC_AGENT_ID:
        logger.warning("ELASTIC_AGENT_ID not set — skipping tool creation.")
        _print_tools()
        return

    headers = {
        "kbn-xsrf": "true",
        "Authorization": f"ApiKey {KIBANA_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        for tool in ESQL_TOOLS:
            tool_id = tool["id"]
            url = f"{KIBANA_URL}/api/agent_builder/tools"
            payload = {**tool}
            try:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code in (200, 201):
                    logger.info(f"✓ Tool '{tool_id}' created.")
                elif resp.status_code == 409:
                    logger.info(f"  Tool '{tool_id}' already exists.")
                else:
                    logger.warning(
                        f"  Tool '{tool_id}' failed ({resp.status_code}): {resp.text}"
                    )
                    logger.warning("  → Create this tool manually in Kibana Agent Builder.")
            except httpx.RequestError as e:
                logger.error(f"  Request error for tool '{tool_id}': {e}")


def _print_tools():
    """Print ES|QL tool definitions for manual entry in Kibana."""
    print("\n── ES|QL Tools for Kibana Agent Builder ──────────────────────────")
    for tool in ESQL_TOOLS:
        print(f"\nTool ID: {tool['id']}")
        print(f"  Description: {tool['description']}")
        print(f"  Query:\n    {tool['configuration']['query']}")
    print("\n──────────────────────────────────────────────────────────────────\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Setup Elasticsearch for Kitsap Commute MCP")
    parser.add_argument("--create-endpoints", action="store_true", help="Create EIS inference endpoints")
    parser.add_argument("--create-index", action="store_true", help="Create events index")
    parser.add_argument("--load-sample-data", action="store_true", help="Load sample_events.json")
    parser.add_argument("--create-tools", action="store_true", help="Create Agent Builder ES|QL tools")
    parser.add_argument("--print-tools", action="store_true", help="Print tool definitions (no API call)")
    parser.add_argument("--all", action="store_true", help="Run all setup steps")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        sys.exit(0)

    if args.all or args.create_endpoints:
        create_inference_endpoint()
        create_reranker_endpoint()

    if args.all or args.create_index:
        create_event_index()

    if args.all or args.load_sample_data:
        load_sample_events()

    if args.all or args.create_tools:
        create_agent_tools()

    if args.print_tools:
        _print_tools()
