"""
Centralized configuration for Kitsap Commute MCP servers.
Loads environment variables and validates required settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"

# --- WSDOT & Google Maps ---
WSDOT_API_KEY = os.getenv("WSDOT_API_KEY")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# --- Elasticsearch ---
ELASTIC_ENDPOINT = os.getenv("ELASTIC_ENDPOINT", "http://localhost:9200")
ELASTIC_API_KEY = os.getenv("ELASTIC_API_KEY")
EVENT_INDEX = os.getenv("EVENT_INDEX", "events")

# --- Kibana / Agent Builder ---
def _derive_kibana_url(es_url: str) -> str:
    """Derive Kibana URL from Elasticsearch URL (Elastic Cloud pattern)."""
    if ".es." in es_url:
        return es_url.replace(".es.", ".kb.")
    return ""

KIBANA_URL = os.getenv("KIBANA_URL") or _derive_kibana_url(ELASTIC_ENDPOINT)
KIBANA_API_KEY = os.getenv("KIBANA_API_KEY") or ELASTIC_API_KEY
ELASTIC_AGENT_ID = os.getenv("ELASTIC_AGENT_ID", "")

# --- Elastic Inference Service (Jina models) ---
INFERENCE_ENDPOINT_ID = os.getenv("INFERENCE_ENDPOINT_ID", "jina-embeddings-v5-text-small")
RERANKER_ENDPOINT_ID = os.getenv("RERANKER_ENDPOINT_ID", "jina-reranker-v3")
JINA_EMBEDDING_MODEL = "jina-embeddings-v5-text-small"
JINA_RERANKER_MODEL = "jina-reranker-v3"


class _Config:
    """Namespace object for compatibility with elastic_agent_example.py."""
    KIBANA_URL = KIBANA_URL
    KIBANA_API_KEY = KIBANA_API_KEY
    ELASTICSEARCH_API_KEY = ELASTIC_API_KEY
    ELASTICSEARCH_URL = ELASTIC_ENDPOINT
    ELASTIC_AGENT_ID = ELASTIC_AGENT_ID


config = _Config()
