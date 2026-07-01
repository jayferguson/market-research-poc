"""Polite HTTP fetch + search providers (Brave primary, DDG fallback).

Adapted from workspace SalesCrossSell/python_app/salescrosssell/fetch.py
(for focused market-research-poc product-lines slice; kept independent).

Includes:
- Rate limiting + robots.txt gate
- Clean text extraction (regex strip)
- Brave Search (when key) and duckduckgo-search fallback
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections import defaultdict
from typing import Any

import httpx

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None  # fallback handled gracefully


# ---------------------------------------------------------------------------
# Rate limiter (per-domain token bucket)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, default_qps: float = 1.0, max_burst: int = 3) -> None:
        self._default_qps = default_qps
        self._max_burst = max_burst
        self._tokens: dict[str, float] = defaultdict(lambda: float(max_burst))
        self._last_refill: dict[str, float] = defaultdict(time.monotonic)

    def wait(self, domain: str, qps: float | None = None) -> None:
        rate = qps or self._default_qps
        now = time.monotonic()
        elapsed = now - self._last_refill[domain]
        self._tokens[domain] = min(float(self._max_burst), self._tokens[domain] + elapsed * rate)
        self._last_refill[domain] = now
        if self._tokens[domain] < 1.0:
            deficit = 1.0 - self._tokens[domain]
            time.sleep(deficit / rate)
            self._tokens[domain] = 1.0
        self._tokens[domain] -= 1.0


GLOBAL_LIMITER = RateLimiter(default_qps=1.0, max_burst=3)


# ---------------------------------------------------------------------------
# robots.txt (cached, permissive on failure)
# ---------------------------------------------------------------------------

_robots_cache: dict[str, str | None] = {}
_robots_fetched_at: dict[str, float] = {}
_ROBOTS_TTL = 3600.0


def _domain_from_url(url: str) -> str:
    return urllib.parse.urlparse(url).netloc


def allows_url(url: str, user_agent: str = "MarketResearchPoC/1.0") -> bool:
    domain = _domain_from_url(url)
    now = time.monotonic()
    if domain in _robots_cache and now - _robots_fetched_at.get(domain, 0) < _ROBOTS_TTL:
        rules = _robots_cache[domain]
    else:
        try:
            resp = httpx.get(f"https://{domain}/robots.txt", timeout=8.0, follow_redirects=True)
            rules = resp.text if resp.status_code == 200 else None
        except Exception:
            rules = None
        _robots_cache[domain] = rules
        _robots_fetched_at[domain] = now
    if not rules:
        return True
    # Very simple parser: look for User-agent * and Disallow for path
    lines = [l.strip().lower() for l in rules.splitlines() if l.strip() and not l.strip().startswith("#")]
    agent = "*"
    disallows: list[str] = []
    for l in lines:
        if l.startswith("user-agent:"):
            agent = l.split(":", 1)[1].strip()
        if agent in ("*", user_agent.lower()) and l.startswith("disallow:"):
            path = l.split(":", 1)[1].strip()
            if path:
                disallows.append(path)
    parsed = urllib.parse.urlparse(url)
    for d in disallows:
        if d == "/" or parsed.path.startswith(d):
            return False
    return True


# ---------------------------------------------------------------------------
# Page fetch
# ---------------------------------------------------------------------------

def fetch_page_text(
    url: str,
    max_chars: int = 14000,
    *,
    check_robots: bool = True,
    rate_limit: bool = True,
    user_agent: str = "Mozilla/5.0 (compatible; MarketResearchPoC/1.0)",
) -> str:
    if not url or not url.startswith(("http://", "https://")):
        return ""
    domain = _domain_from_url(url)
    if check_robots and not allows_url(url, user_agent):
        return f"[fetch blocked by robots.txt for {url}]"
    if rate_limit:
        GLOBAL_LIMITER.wait(domain)
    try:
        headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
        with httpx.Client(follow_redirects=True, timeout=25.0, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        # Basic clean (same spirit as SalesCrossSell)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

        # meta desc
        meta = ""
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
        if m:
            meta = m.group(1).strip() + " "

        full = (meta + text).strip()
        return full[:max_chars]
    except Exception as e:
        return f"[fetch error for {url}: {str(e)[:120]}]"


# ---------------------------------------------------------------------------
# Search providers
# ---------------------------------------------------------------------------

def brave_search(query: str, api_key: str, count: int = 10) -> list[dict[str, Any]]:
    """Brave Search (web) - mirrors SalesCrossSell implementation."""
    if not api_key:
        return []
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": min(count, 20)}
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
        results = []
        for item in (data.get("web", {}).get("results", []) or []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        return results
    except Exception:
        return []


def ddg_search(query: str, count: int = 10) -> list[dict[str, Any]]:
    """DuckDuckGo fallback (no key required)."""
    if DDGS is None:
        return []
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=count))
        return [
            {"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")}
            for h in hits
        ]
    except Exception:
        return []


def search_for_product_lines(company_name: str, brave_key: str = "", count: int = 12) -> list[dict[str, Any]]:
    """Targeted queries for product line discovery."""
    queries = [
        f'"{company_name}" "product lines" OR "product line" OR divisions OR portfolio OR "business units" OR offerings',
        f"{company_name} official products catalog OR solutions",
        f'"{company_name}" "our brands" OR "our divisions"',
    ]
    all_results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in queries:
        if brave_key:
            hits = brave_search(q, brave_key, count=count // len(queries) + 2)
        else:
            hits = ddg_search(q, count=count // len(queries) + 2)
        for h in hits:
            u = h.get("url", "")
            if u and u not in seen:
                seen.add(u)
                all_results.append(h)
    return all_results[:count]
