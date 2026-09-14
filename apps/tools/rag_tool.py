"""Vertex AI RAG retrieval with a session-scoped cache."""

from __future__ import annotations

import asyncio
import hashlib
import logging

import vertexai.rag as vrag
from google.adk.tools import ToolContext
from vertexai.rag.utils.resources import RagResource, RagRetrievalConfig

from apps.config import settings

logger = logging.getLogger(__name__)

_TOP_K = 3


def _parse_contexts(response) -> list[dict[str, str]]:
    """Extract compact text and source fields from a RAG response."""
    contexts = getattr(response, "contexts", None)
    chunks = getattr(contexts, "contexts", []) if contexts else []
    return [
        {
            "text": getattr(chunk, "text", ""),
            "source": getattr(chunk, "source_display_name", "KHIND documents"),
        }
        for chunk in chunks
        if getattr(chunk, "text", "")
    ]


async def query_product_info(query: str, tool_context: ToolContext) -> dict:
    """Search verified KHIND product, pricing, promotion, and coverage documents.

    Call for product follow-up questions, prices, promotions, warranty, dimensions,
    delivery coverage, and application eligibility. Include the selected product name
    and the specific topic in the query. Never infer facts that are absent from results.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {"status": "empty", "results": []}

    cache_generation = tool_context.state.get("rag_cache_generation", 0)
    query_hash = hashlib.sha256(cleaned_query.lower().encode()).hexdigest()[:12]
    cache_key = f"rag_{cache_generation}_{query_hash}"
    cached_result = tool_context.state.get(cache_key)
    if cached_result is not None:
        return cached_result

    try:
        response = await asyncio.to_thread(
            vrag.retrieval_query,
            text=cleaned_query,
            rag_resources=[RagResource(rag_corpus=settings.vertex_rag_corpus)],
            rag_retrieval_config=RagRetrievalConfig(top_k=_TOP_K),
        )
        result = {"status": "ok", "results": _parse_contexts(response)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("KHIND RAG query failed")
        result = {"status": "error", "results": [], "rag_error": True}

    tool_context.state[cache_key] = result
    return result

## Suggestion for caching rag via rag engine semantic 


"""
semantic caching interprets and stores semantic meaning of user queries allowing system to retrieve relevant information more efficiently even if the exact query text differs.'
this method allow for more nuanced data interactions where the cache surfqce response that are more relevant that traditional caching an faster than typical response from LLM 

it work by converting queries into vector embedding 1536 dim and measure similarity betwen vectors 

if exced > 0.95 , the system return the cached response instead of calling LLM 

"""


"""
Proposal to build 

Via Vertex AI RAG Engine 

1. query embedding 
2. cach lookup 
- query embed vs cached embeddings > 0.9 cosine similarity 
- cache miss 
- no match then run RAG 
"""