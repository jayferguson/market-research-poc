"""Product lines research orchestration for Market Research PoC.

First feature slice: given company name → determine product lines (high-level).

Uses ResearchContext for testability (no Flet/UI coupling).
Adapted patterns from SalesCrossSell research/pipeline + fetch/llm (standalone copy).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from openai import OpenAI

from . import storage as st
from .fetch import fetch_page_text, search_for_product_lines, brave_search, ddg_search
from .llm import llm_analyze, _extract_json

from market_research.config import load_settings  # absolute import for reliable loading under python -m


class UsageTracker(Protocol):
    def __call__(self, usage: dict[str, Any]) -> None: ...


@dataclass
class ResearchContext:
    llm_client: OpenAI | None = None
    model: str = "grok-4.3-latest"
    status_callback: Callable[[str], None] | None = None
    track_usage: UsageTracker | None = None
    db_path: str = "market_research.db"
    brave_api_key: str = ""


def _status(ctx: ResearchContext, msg: str) -> None:
    if ctx.status_callback:
        ctx.status_callback(msg)


def find_official_website(company_name: str, ctx: ResearchContext) -> str:
    """Find primary company site via Brave (or DDG) + LLM fallback."""
    if ctx.brave_api_key:
        results = brave_search(f"{company_name} official website", ctx.brave_api_key, count=5)
        for r in results:
            url = r.get("url", "")
            title = (r.get("title", "") or "").lower()
            if company_name.lower() in title or "official" in title:
                if not url.startswith("https://en.wikipedia"):
                    return url.rstrip("/")
    # Fallback LLM
    prompt = (
        f"Return ONLY the official website URL (https://...) for the company '{company_name}'. "
        "No other text."
    )
    text, _ = llm_analyze(
        prompt,
        system="Return only a clean URL.",
        client=ctx.llm_client,
        model=ctx.model,
    )
    m = re.search(r"https?://[^\s\"'<>]+", text)
    return (m.group(0).rstrip("/") if m else "") or ""


def discover_pages(company_name: str, main_site: str, ctx: ResearchContext) -> list[str]:
    """Return promising URLs for product line extraction (search + common paths)."""
    pages: list[str] = []
    if main_site:
        base = main_site.rstrip("/")
        for suffix in ("", "/products", "/solutions", "/about", "/investors", "/brands", "/portfolio"):
            pages.append(base + suffix if suffix else base)

    # Search hits
    search_hits = search_for_product_lines(company_name, ctx.brave_api_key, count=8)
    for h in search_hits:
        u = h.get("url", "")
        if u and u not in pages:
            pages.append(u)
    # Dedup + limit
    seen = set()
    out = []
    for p in pages:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:15]


def extract_product_lines_from_content(
    company_name: str, combined_content: str, ctx: ResearchContext
) -> list[dict[str, Any]]:
    """LLM structured extraction. Explicit 'product line' guidance."""
    if not combined_content.strip():
        return []

    prompt = (
        f"You are a precise B2B market researcher.\n\n"
        f"A 'product line' is a major high-level group, division, brand family, or portfolio category "
        f"of related offerings (e.g. 'Industrial Adhesives', 'Healthcare Solutions', 'Safety & Graphics'). "
        f"IGNORE individual SKUs, specific models, or one-off products.\n\n"
        f"Company: {company_name}\n\n"
        f"Content (website pages + search):\n{combined_content[:16000]}\n\n"
        f"Extract ALL distinct major product lines you can find from the content. Be exhaustive and consistent across runs.\n"
        f"For each return a JSON object with:\n"
        f'  "name": "short canonical name",\n'
        f'  "description": "1-2 sentence summary of what this line covers",\n'
        f'  "key_products_or_services": ["2-4 representative examples"],\n'
        f'  "subsidiary": "name of the subsidiary/brand/division this line belongs to (null or omit if it is a main company line)",\n'
        f'  "evidence": [{{"url": "...", "quote": "short supporting text from content"}}]\n\n'
        f"Return ONLY a JSON array. Aim for completeness of the company's main lines/divisions (including those of subsidiaries). If none, return []."
    )
    text, usage = llm_analyze(
        prompt,
        system="You are a precise extractor. Return ONLY the requested JSON array. Be exhaustive for high-level product lines.",
        client=ctx.llm_client,
        model=ctx.model,
        max_tokens=2800,
        # Low temperature for more consistent/deterministic product line extraction across runs
        temperature=0.2,
    )
    if ctx.track_usage:
        ctx.track_usage(usage)

    data = _extract_json(text) or []
    if not isinstance(data, list):
        data = data.get("product_lines") or data.get("lines") or []
    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        sub = item.get("subsidiary")
        if isinstance(sub, str):
            sub = sub.strip() or None
        cleaned.append({
            "name": name,
            "description": (item.get("description") or "").strip(),
            "key_products_or_services": item.get("key_products_or_services") or [],
            "subsidiary": sub,
            "evidence": item.get("evidence") or [],
        })
    return cleaned


def find_subsidiaries(company_name: str, main_website: str, ctx: ResearchContext) -> list[dict[str, str]]:
    """Discover subsidiaries + websites using search + LLM extraction.

    Returns list of {"name": , "website": , "area": }
    """
    result_map: dict[str, dict[str, str]] = {}

    # Search
    query = f'"{company_name}" (subsidiaries OR divisions OR "operating companies" OR brands)'
    if ctx.brave_api_key:
        search_results = brave_search(query, ctx.brave_api_key, count=10)
    else:
        search_results = ddg_search(query, count=10)

    fetched = []
    for sr in search_results[:8]:
        url = sr.get("url", "")
        if not url:
            continue
        text = fetch_page_text(url)
        if text and not text.startswith("[fetch"):
            fetched.append(f"--- URL: {url}\n{text[:4000]}")

    if fetched:
        combined = "\n\n".join(fetched)[:18000]
        prompt = (
            f"From the following real web pages about {company_name}, extract every distinct subsidiary, "
            f"brand, or operating division.\n\n{combined}\n\n"
            f"For each return name, website (if known), and short business_area/focus.\n"
            f'Return ONLY a JSON array like: [{{"name": "Harvard Apparatus", "website": "https://...", "area": "Fluidics"}}]\n'
            f"Be accurate and deduplicate."
        )
        text, usage = llm_analyze(
            prompt,
            system="Extract clean list of subsidiaries as JSON array only.",
            client=ctx.llm_client,
            model=ctx.model,
            max_tokens=2000,
        )
        if ctx.track_usage:
            ctx.track_usage(usage)
        data = _extract_json(text) or []
        if isinstance(data, list):
            for item in data:
                nm = (item.get("name") or "").strip()
                if nm:
                    key = nm.lower()
                    result_map[key] = {
                        "name": nm,
                        "website": (item.get("website") or "").strip(),
                        "area": (item.get("area") or item.get("business_area") or "").strip(),
                    }

    # Fallback supplement with LLM knowledge if very few
    if len(result_map) < 2:
        prompt = (
            f"List known subsidiaries, divisions and brands of {company_name}. "
            f"Return ONLY JSON array of objects with name, website (if known), area."
        )
        text, _ = llm_analyze(prompt, client=ctx.llm_client, model=ctx.model)
        data = _extract_json(text) or []
        if isinstance(data, list):
            for item in data:
                nm = (item.get("name") or "").strip()
                if nm and nm.lower() not in result_map:
                    result_map[nm.lower()] = {
                        "name": nm,
                        "website": (item.get("website") or "").strip(),
                        "area": (item.get("area") or "").strip(),
                    }

    return list(result_map.values())


def extract_product_lines_for_entity(
    entity_name: str,
    entity_website: str,
    main_company_name: str,
    ctx: ResearchContext,
    is_main: bool = False
) -> list[dict[str, Any]]:
    """Targeted extraction for one specific entity (the main company or one subsidiary).

    This is much more accurate for attribution than a single mixed scrape + LLM guessing.
    We fetch from the entity's own website (if known) + run entity-specific search.
    The prompt forces the LLM to only return lines for this entity.
    """
    if not entity_name:
        return []

    contents: list[str] = []

    # 1. Pages directly from the entity's own website (best source)
    if entity_website:
        base = entity_website.rstrip("/")
        for suffix in ("", "/products", "/solutions", "/catalog", "/portfolio", "/brands"):
            url = base + suffix if suffix else base
            txt = fetch_page_text(url)
            if txt and not txt.startswith("[fetch"):
                contents.append(f"--- URL: {url}\n{txt[:4500]}")

    # 2. Entity-specific web search (critical for catching product info)
    q = f'"{entity_name}" ("product lines" OR portfolio OR "solutions" OR offerings OR "business units")'
    search_hits_local: list[dict] = []
    if ctx.brave_api_key:
        search_hits_local = brave_search(q, ctx.brave_api_key, count=7)
    else:
        search_hits_local = ddg_search(q, count=7)

    for h in search_hits_local[:6]:
        url = h.get("url", "")
        if not url:
            continue
        txt = fetch_page_text(url)
        if txt and not txt.startswith("[fetch"):
            contents.append(
                f"--- SEARCH for {entity_name}: {url}\n{h.get('snippet', '')}\n{txt[:3000]}"
            )

    combined = "\n\n".join(contents)[:20000]
    if not combined:
        return []

    sub_instruction = "null" if is_main else f'"{entity_name}"'

    prompt = (
        f'You are a precise B2B market researcher. Extract product lines **only for the specific entity "{entity_name}"** '
        f'(a subsidiary/division/brand of the larger company "{main_company_name}").\n\n'
        f'A "product line" is a major high-level group, division, brand family, or portfolio category of related offerings. '
        f'IGNORE individual SKUs, specific models, or one-off products.\n\n'
        f'All content below is directly from or about {entity_name} (its website + targeted searches):\n\n'
        f'{combined}\n\n'
        f'Extract ONLY lines that belong to {entity_name}.\n'
        f'For each return a JSON object:\n'
        f'  "name": "short canonical name",\n'
        f'  "description": "1-2 sentence summary",\n'
        f'  "key_products_or_services": ["2-4 examples"],\n'
        f'  "subsidiary": {sub_instruction},\n'
        f'  "evidence": [{{"url": "...", "quote": "short supporting text"}}]\n\n'
        f'Return ONLY a JSON array. Be strict: do not invent lines or attribute lines from other parts of the company to this entity.'
    )

    text, usage = llm_analyze(
        prompt,
        system="Return ONLY the requested JSON array for the exact entity specified. No prose, no other entities.",
        client=ctx.llm_client,
        model=ctx.model,
        max_tokens=2800,
        temperature=0.1,
    )
    if ctx.track_usage:
        ctx.track_usage(usage)

    data = _extract_json(text) or []
    if not isinstance(data, list):
        data = data.get("product_lines") or data.get("lines") or []

    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        nm = (item.get("name") or "").strip()
        if not nm:
            continue
        sub = item.get("subsidiary")
        if isinstance(sub, str):
            sub = sub.strip() or (None if is_main else entity_name)
        else:
            sub = None if is_main else entity_name
        cleaned.append({
            "name": nm,
            "description": (item.get("description") or "").strip(),
            "key_products_or_services": item.get("key_products_or_services") or [],
            "subsidiary": sub,
            "evidence": item.get("evidence") or [],
        })
    return cleaned


def determine_product_lines(ctx: ResearchContext) -> list[dict[str, Any]]:
    """Main entry for v0.1: (fixed) company + subsidiaries → product lines (with sources persisted).

    The target company comes from settings (TARGET_COMPANY). This PoC is intentionally
    simplified to one company + its subsidiaries only.
    """
    company_name = load_settings().target_company
    _status(ctx, f"Starting product lines research for {company_name} (and subsidiaries)...")

    # 1. Website
    website = find_official_website(company_name, ctx)
    _status(ctx, f"Found website: {website or '(none)'}")

    cid = st.upsert_company(company_name, website, db_path=ctx.db_path)

    # Refresh subsidiaries for freshness (parallel to product lines)
    _status(ctx, "Refreshing subsidiary list for company...")
    st.clear_subsidiaries_for_company(cid, db_path=ctx.db_path)

    subs = find_subsidiaries(company_name, website, ctx)
    for sub in subs:
        st.upsert_subsidiary(
            cid, sub["name"], sub.get("website", ""), sub.get("area", ""), db_path=ctx.db_path
        )
    _status(ctx, f"Found {len(subs)} subsidiaries.")

    # Broad search hits (used later for attaching some general sources to lines)
    search_hits = search_for_product_lines(company_name, ctx.brave_api_key, count=6)

    # 2. Per-entity targeted research (the key fix for correct subsidiary attribution)
    # Instead of one big mixed scrape + LLM guessing "which sub this belongs to",
    # we now research the main company and each subsidiary *separately*:
    # - Fetch pages from that entity's own website (if we have it)
    # - Run entity-specific search
    # - Prompt the LLM with the exact entity name and "only return lines for this entity"
    _status(ctx, "Extracting product lines separately for the main company and each subsidiary...")

    entities = [{"name": company_name, "website": website, "is_main": True}]
    for s in subs:
        entities.append({
            "name": s["name"],
            "website": s.get("website", ""),
            "is_main": False
        })

    lines: list[dict[str, Any]] = []
    for ent in entities:
        _status(ctx, f"  - {ent['name']} ...")
        ent_lines = extract_product_lines_for_entity(
            ent["name"], ent["website"], company_name, ctx, ent["is_main"]
        )
        lines.extend(ent_lines)

    # Deduplicate (name + subsidiary) across all entities
    seen = set()
    deduped = []
    for ln in lines:
        key = (ln["name"].lower().strip(), (ln.get("subsidiary") or "").lower().strip())
        if key[0] and key not in seen:
            seen.add(key)
            deduped.append(ln)
    lines = deduped

    _status(ctx, f"Total unique product lines after per-entity extraction: {len(lines)}")

    # 4. Refresh lines for this company (clear previous to avoid accumulation from
    # prior runs + LLM variance) then persist fresh results. This keeps a clean
    # "current best view".
    _status(ctx, "Refreshing stored product lines for company (removing previous run data)...")
    st.clear_product_lines_for_company(cid, db_path=ctx.db_path)

    _status(ctx, f"Persisting {len(lines)} product lines...")
    for ln in lines:
        lid = st.insert_product_line(
            cid,
            ln["name"],
            ln.get("description", ""),
            ln.get("key_products_or_services", []),
            "",  # verticals hint later
            subsidiary=ln.get("subsidiary"),
            db_path=ctx.db_path,
            skip_if_exists=True,  # extra safety
        )
        if lid == -1:
            continue  # skipped duplicate
        # Evidence sources
        for ev in ln.get("evidence", []):
            st.insert_line_source(
                lid,
                url=ev.get("url", ""),
                title="",
                query_used="product-lines-extract",
                snippet=ev.get("quote", "")[:400],
                db_path=ctx.db_path,
            )
        # Also attach top search hits as general sources for the line
        for h in search_hits[:2]:
            st.insert_line_source(
                lid,
                url=h.get("url", ""),
                title=h.get("title", ""),
                query_used="search-for-product-lines",
                snippet=h.get("snippet", "")[:300],
                db_path=ctx.db_path,
            )

    _status(ctx, f"Completed. Stored {len(lines)} product lines and {len(subs)} subsidiaries for {company_name} (refreshed).")
    return st.list_product_lines_with_sources(cid, db_path=ctx.db_path)
