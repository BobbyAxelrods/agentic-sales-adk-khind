"""Vertex AI RAG retrieval, limited to the product's own document, with a session cache.

A search over the whole corpus ranks other products' documents above the one asked
about (smoke test 2026-09-24: 592L price and weight answers came from the Lite 480L
document). So a query that names a product, or runs while a product is active, only
searches that product's corpus file.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re

import vertexai
import vertexai.rag as vrag
from google.adk.tools import ToolContext
from vertexai.rag.utils.resources import RagResource, RagRetrievalConfig

from apps.config import settings
from apps.services.replies import REPLY_FACTS_KEY
from apps.tools.session_tools import find_product_keys, set_product_interest

logger = logging.getLogger(__name__)

_TOP_K_CORPUS = 3
# Product files hold 3-7 chunks, so this returns the whole document.
_TOP_K_PRODUCT = 8

# Corpus file (display name) for each product key.
PRODUCT_DOCUMENTS: dict[str, str] = {
    "chillmaster_592l": "khind_rsf600a_chillmaster_592l_knowledge_base.md",
    "chillmaster_lite_480l": "khind_rf480_chillmaster_lite_knowledge_base.md",
    "chillmaster_x_466l": "khind_rfm466a_chillmasterx_466l_knowledge_base.md",
    "washer_dryer_11_7": "khind_wd1468_washer_dryer_knowledge_base.md",
    "front_load_9kg": "khind_wm1248_9kg_washer_knowledge_base.md",
    "ecowash_top_15kg": "khind_wm150a_ecowash15_knowledge_base.md",
    "drymaster_9kg": "khind_dhp90_drymaster_heatpump_dryer_knowledge_base.md",
    "aircond_kool_series": "khind_acson_knowledge_base.md",
}

# Display name -> file id, loaded once per process. A failed load is not kept.
_file_ids: dict[str, str] | None = None
_CORPUS_PATH = re.compile(r"^projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/ragCorpora/")


def _load_file_ids() -> dict[str, str]:
    """Map each corpus display name to the id of its newest file.

    The corpus holds two uploads of some documents; the older copy is ignored.
    """
    # The SDK sends list_files to the region of its global config, which defaults to
    # us-central1 (it does not read GOOGLE_CLOUD_LOCATION), so point it at the corpus's
    # own project and region first.
    corpus = _CORPUS_PATH.match(settings.vertex_rag_corpus)
    if corpus:
        vertexai.init(project=corpus["project"], location=corpus["location"])
    newest: dict[str, tuple[float, str]] = {}
    for rag_file in vrag.list_files(corpus_name=settings.vertex_rag_corpus):
        created = rag_file.create_time.timestamp() if rag_file.create_time else 0.0
        file_id = rag_file.name.rsplit("/", 1)[-1]
        name = rag_file.display_name
        if name in newest:
            logger.warning("RAG corpus holds %s more than once; using the newest upload", name)
        if name not in newest or created > newest[name][0]:
            newest[name] = (created, file_id)
    return {name: file_id for name, (_, file_id) in newest.items()}


async def _product_file_ids(products: list[str], refresh: bool = False) -> list[str]:
    global _file_ids
    if _file_ids is None or refresh:
        try:
            _file_ids = await asyncio.to_thread(_load_file_ids)
        except Exception:  # noqa: BLE001
            logger.exception("Listing the KHIND RAG corpus files failed")
    known = _file_ids or {}
    return [known[PRODUCT_DOCUMENTS[key]] for key in products if PRODUCT_DOCUMENTS.get(key) in known]


def _retrieve(query: str, file_ids: list[str] | None, top_k: int):
    return vrag.retrieval_query(
        text=query,
        rag_resources=[RagResource(rag_corpus=settings.vertex_rag_corpus, rag_file_ids=file_ids or None)],
        rag_retrieval_config=RagRetrievalConfig(top_k=top_k),
    )


async def _search(query: str, products: list[str]) -> dict:
    """Search the named products' files, or the whole corpus when none is known."""
    if products:
        file_ids = await _product_file_ids(products)
        if file_ids:
            try:
                chunks = _parse_contexts(await asyncio.to_thread(_retrieve, query, file_ids, _TOP_K_PRODUCT))
            except Exception:  # noqa: BLE001
                logger.warning("Scoped RAG query failed; reloading the file ids once", exc_info=True)
                chunks = []
            if not chunks:
                # The ids may be stale after a corpus change: reload them and retry once.
                file_ids = await _product_file_ids(products, refresh=True)
                if file_ids:
                    chunks = _parse_contexts(await asyncio.to_thread(_retrieve, query, file_ids, _TOP_K_PRODUCT))
            if file_ids:
                return {"status": "ok", "scope": "product", "products": products, "results": chunks}
        logger.warning("No corpus file found for %s; searching the whole corpus", products)
    response = await asyncio.to_thread(_retrieve, query, None, _TOP_K_CORPUS)
    return {"status": "ok", "scope": "corpus", "products": [], "results": _parse_contexts(response)}


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
    """Search verified KHIND product documents: prices, promotions, warranty, dimensions, specs.

    Name the product and the topic in the query (e.g. "harga bulanan ChillMaster 592L").
    The search covers only the document of the product named in the query, or of the
    active product when none is named. With no active product, a query that names one
    product also selects it (as set_product_interest would). If the customer moves to
    another product, call set_product_interest first. If the results do not state the
    answer, send the missing-fact line and carry on: that is not a handoff. Never use
    figures from another product's document, and never infer facts that are absent from
    the results.
    Do NOT call this tool for location coverage (advance_purchase_stage checks it).
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {"status": "empty", "results": []}
    # The reply carries this turn's answer (see insert_pending_usp).
    tool_context.state[REPLY_FACTS_KEY] = tool_context.invocation_id

    # The query names the product even when state is not updated yet (the model can send
    # this call and set_product_interest in one response).
    products = find_product_keys(cleaned_query)
    active_product = tool_context.state.get("product_interest")
    # Before any pick, a question about one product is the pick (the discovery rule). The
    # model sometimes searched without calling set_product_interest (E1): no USP, no
    # location step.
    pick = {}
    if not active_product and len(products) == 1:
        picked = set_product_interest(products[0], tool_context)
        pick = {"product_selected": picked["product_interest"]}
        if picked.get("reply_rule"):
            pick["reply_rule"] = picked["reply_rule"]
    if not products and active_product:
        products = [active_product]

    cache_generation = tool_context.state.get("rag_cache_generation", 0)
    query_hash = hashlib.sha256(cleaned_query.lower().encode()).hexdigest()[:12]
    cache_key = f"rag_{cache_generation}_{'+'.join(products) or 'all'}_{query_hash}"
    cached_result = tool_context.state.get(cache_key)
    if cached_result is not None:
        return {**cached_result, **pick}

    try:
        result = await _search(cleaned_query, products)
    except Exception:  # noqa: BLE001
        logger.exception("KHIND RAG query failed")
        # Not cached, so the next question tries again.
        return {"status": "error", "results": [], "rag_error": True, **pick}

    # A whole-corpus fallback is not stored under a product key.
    if result["scope"] == "product" or not products:
        tool_context.state[cache_key] = result
    return {**result, **pick}

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