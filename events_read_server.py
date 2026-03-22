"""
MCP server for reading events via Elastic Agent Builder.

Sends natural-language queries to the Agent Builder converse API.
The agent uses its configured ES|QL tools to search the events index
and returns a synthesised answer.
"""

import logging
from typing import Optional

from fastmcp import FastMCP
from elastic_agent_example import ElasticAgentClient, ElasticAgentError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("events-read")

_agent_client: Optional[ElasticAgentClient] = None


def get_client() -> ElasticAgentClient:
    global _agent_client
    if _agent_client is None:
        _agent_client = ElasticAgentClient()
    return _agent_client


@mcp.tool(
    name="search_events",
    description=(
        "Search the events index using natural language. The Elastic Agent interprets "
        "your query and runs the appropriate ES|QL tools internally. Ask things like "
        "'What tech events are coming up next month?' or 'Am I presenting anywhere in February?'."
    ),
)
def search_events(
    query: str,
    conversation_id: Optional[str] = None,
) -> dict:
    """
    Send a natural-language query to the Elastic Agent Builder.

    Args:
        query: Natural-language question about events.
        conversation_id: Optional — pass back a prior conversation_id for multi-turn context.

    Returns:
        {
            "response": str,          # The agent's answer
            "conversation_id": str,   # Pass this back for follow-up questions
        }
    """
    try:
        result = get_client().chat(input=query, conversation_id=conversation_id)
        return {
            "response": result.get("response", ""),
            "conversation_id": result.get("conversation_id", ""),
        }
    except ElasticAgentError as e:
        logger.error(f"Agent error: {e}")
        return {"error": str(e), "response": "", "conversation_id": ""}


if __name__ == "__main__":
    mcp.run()
