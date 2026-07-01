# Future Improvements & Alternatives

This file captures ideas for improving the Market Research PoC, particularly around accurate attribution of product lines to the main company vs. its subsidiaries.

## Current Problem (as of v0.3)
Product lines were frequently attributed to "Main Company" even when they belonged to subsidiaries. 
The original approach used a single broad scrape + search of mixed content and relied on the LLM to tag the correct `subsidiary` in the JSON output. 
LLM attribution from noisy/mixed content is unreliable.

## Implemented Fix (v0.3)
- After discovering subsidiaries (with their websites when available), we now perform **per-entity targeted research**.
- For the main company **and each subsidiary**:
  - Fetch pages directly from the entity's own website (if known) + run entity-specific searches.
  - Use a tightly-scoped LLM prompt that says "extract ONLY for this exact entity".
  - Post-process to set `subsidiary = null` (main) or the exact subsidiary name.
- This drives attribution primarily from the *source of the content* rather than LLM guessing.

See `pipeline.py` (the `extract_product_lines_for_entity` helper and the loop over `entities` in `determine_product_lines`).

## Alternatives & Ideas to Explore Later

1. **Stronger Post-Extraction Validation Layer**
   - After LLM extraction, for every line that claims a `subsidiary`, inspect its `evidence[].url` domains.
   - Cross-check against the known list of subsidiary websites (from the `subsidiaries` table).
   - If the evidence URL does not match the claimed subsidiary (or a subdomain), either:
     - Downgrade to "Main Company" / "Unclear"
     - Flag with low confidence
     - Drop the line or move it to a review queue
   - This adds a deterministic "source of truth" check on top of the LLM.

2. **Aggressive site: Operator Boost**
   - In `extract_product_lines_for_entity`, when we have a subsidiary website, also run:
     `brave_search(f'"{entity_name}" product lines OR portfolio site:{netloc}')`
   - This gives much cleaner, higher-precision content that is already guaranteed to be from the right site.
   - Combine with the general search as a fallback.

3. **Subsidiary Website Enrichment on Product Lines**
   - Denormalize `subsidiary_website` onto the `product_lines` row at insert time (or store a small dict/object).
   - Makes the UI lookup for clickable links faster and more reliable (no need to join/lookup at display time).
   - Useful if we ever export data or build reports.

4. **Closed-Set / Structured LLM Output**
   - Pass the full list of known entity names (main + all subsidiaries) into the prompt as a closed set.
   - Instruct the model: "subsidiary field MUST be exactly one of: null, 'Main Company', 'Harvard Apparatus', 'Warner Instruments', ... (list them)".
   - Use JSON mode / structured outputs (if the provider supports it) or a grammar.
   - Reduces hallucinated subsidiary names.

5. **Hybrid Extraction Strategy**
   - Primary signal: per-entity scrape + scoped prompt (current v0.3).
   - Secondary / fallback signal: a light "broad company scan" that is only used to fill gaps for entities that had very little own-site content.
   - Run a cheap consistency/ensemble step: "given this line name + these evidence URLs, which of the known entities is the best match?"

6. **Confidence Scoring & Human Review**
   - Have the LLM also return a `confidence` (0-100) and/or `reasoning` for the attribution.
   - Surface low-confidence lines in the UI (e.g., yellow badge, separate "Review" tab).
   - Add a simple curation UI to correct subsidiary on a line (and persist the correction so future runs can learn from it).

7. **Better Subsidiary Discovery (upstream)**
   - Improve `find_subsidiaries` to also pull "last known website" from official sources (SEC filings, company "about us / our brands" pages, Wikipedia infoboxes, etc.).
   - Store `last_verified` date on subsidiaries and re-check periodically.

8. **Parallel / Async Research**
   - The per-entity loop is currently sequential. Run the fetches + LLM calls for main + all subs in parallel (asyncio + httpx or threads).
   - Add progress reporting per entity.

9. **Evaluation / Ground Truth**
   - Pick 2-3 well-known companies with clear public subsidiary structures.
   - Manually label a small set of product lines + correct subsidiary.
   - Use this as a regression test / eval set when changing prompts or extraction logic.
   - Track "attribution accuracy" metric over time.

10. **Export / Reporting**
    - Add export of the current research (JSON, CSV, or even a small HTML report) that includes the subsidiary attribution and evidence links.
    - Useful for the "identify sales opportunities" future slice.

## How to Use This File
- Treat entries as a backlog / parking lot.
- When starting work on a new slice (vertical markets, sales opportunities, etc.), review this list for relevant improvements.
- Feel free to expand or prioritize items.

Last updated: 2026-07-01 (v0.3)

