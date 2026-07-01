# Market Research PoC

**Simplified scope**: This app is configured for **one specific company and its subsidiaries** (not a multi-company database tool).

**Current slice (v0.1)**: For the configured company + subsidiaries, determine product lines (high-level groups/divisions/portfolio categories — not individual SKUs).

Future planned slices (after verification):
- Determine vertical market(s) served/targeted by the lines.
- Identify sales opportunities for a given product line + vertical market.

All research is local-first, citable (sources + evidence snippets), re-runnable (refreshes data), and persisted in SQLite.

The target company is set via `TARGET_COMPANY` in `.env` (see below). The UI/CLI no longer asks for a company name on every run.

## Setup (Windows pwsh + optional WSL)

```powershell
cd C:\Users\fergu\market-research-poc
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create `.env` (copy from `.env.example`):

```
XAI_API_KEY=your_xai_or_openai_key_here
# For local LLM (LM Studio / Ollama openai-compat):
# OPENAI_BASE_URL=http://localhost:1234/v1
# OPENAI_API_KEY=not-needed
BRAVE_API_KEY=your_brave_search_key_here   # optional but preferred for quality (free tier ok)
```

For Brave: sign up at https://brave.com/search/api/ (rapid small usage free).

For xAI/Grok: use your key (same as other workspace tools). Model defaults to grok-4.3-latest or similar.

## Quick Start (CLI - primary for verification)

The company is configured once in `.env` (`TARGET_COMPANY`).

```powershell
# From project root, activated venv
python -m market_research.cli research
# or with model override
python -m market_research.cli research --model grok-4.3-latest
```

- Shows step-by-step progress for the configured company + subsidiary discovery.
- Outputs rich table of product lines with descriptions + evidence.
- Creates/updates `market_research.db`.
- Re-running research **refreshes** the product lines for the company (old data cleared first). This prevents duplicates.

Other commands:
- `python -m market_research.cli show`   (show current lines for the configured company)
- `python -m market_research.cli clean`  (resets stored lines for the company)

## Streamlit UI (basic interactive)

```powershell
streamlit run app.py
```

The company is taken from your `.env` (`TARGET_COMPANY`).

**Command buttons are in one row at the very top** of the interface:
- 🔍 **Research Product Lines** — runs fresh research (refreshes DB + subsidiaries)
- 🔄 **Reload from DB** — pulls latest from DB (no re-research)
- 🗑️ **Clear Results** — clears the current view

On startup (and after reload/research) the app loads product lines + the list of subsidiaries from the database.

**Subsidiaries list**: each subsidiary name is a **clickable link** that opens its website directly in a new tab (when a website is known). The subsidiary + link is also shown inside the details of each product line.

Product line panes start closed by default.

No need to type the company name.

## Verification (required per iteration)

Run the dedicated verifier (part of every feature slice):

```powershell
python verify_product_lines.py
```

It:
- Researches fixed sample companies (Harvard BioScience, 3M Company, ...).
- Asserts basic quality (≥2 lines, names/descs present, sources attached).
- Writes timestamped JSON report under `reports/`.

Also useful:
```powershell
python -m pytest tests/ -q
```
(for fast unit checks like JSON extraction).
- Prints summary.

**Manual cross-check**: For at least one company, open its official site (products/solutions/about/investor pages) and confirm major lines were captured (or note misses → tune prompt/fetch). Re-run verifier after changes. No regressions on prior samples.

See "Product Line Definition" below and the example prompt in `market_research/pipeline.py`.

## Product Line Definition (for this PoC)

A **product line** is a major high-level group, division, brand family, or portfolio category of related offerings.

Examples (good):
- "Industrial Adhesives & Tapes"
- "Healthcare IT Solutions"
- "Safety & Industrial"

Bad (too granular — we filter these out):
- "Scotch Magic Tape 810"
- "PHD 2000 Syringe Pump"

The LLM prompt explicitly instructs "high-level ... not individual SKUs".

## Iteration & Development

- Features added one slice at a time.
- Every change to research (fetch, prompt, post-processing) must pass `verify_product_lines.py` + manual spot-check before considered done.
- Use status callbacks everywhere for visibility.
- ResearchContext for easy mocking/testing of pipeline steps.
- Code adapted from proven workspace patterns (SalesCrossSell fetch/llm/pipeline/db + AIE Streamlit/verify styles) but kept 100% standalone.

See `verify_product_lines.py` and the plan.md in the Grok session for the approved approach and verification process.

## Next Slices (roadmap, not yet implemented)

1. Vertical market determination (for the company or per line).
2. Sales opportunity identification (product line X fits vertical Y for target customer signals).

These will reuse/extend the same storage, fetch, LLM, CLI/Streamlit skeleton.

## Tech Notes

- Brave Search (primary) + DuckDuckGo fallback for discovery.
- Polite httpx fetch (robots.txt, rate limiting, clean text).
- OpenAI-compatible client (Grok at api.x.ai or local LLM servers).
- Robust JSON extraction from LLM (handles markdown, minor syntax issues).
- SQLite with citation tables (urls + snippets for every line).
- No Playwright in v0.1 (http sufficient for public marketing pages).

For advanced JS sites later: consider optional playwright or the chrome-devtools MCP available in this environment.

## License / Status

Internal PoC. Evolving iteratively with verification at each step.
