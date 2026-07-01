"""Verification script for product lines slice (v0.1).

Simplified single-company mode (TARGET_COMPANY + subsidiaries).

Run after any change to fetch / prompts / extraction / post-processing.
- Runs against the configured TARGET_COMPANY
- Basic quality gates (len, names, sources)
- Writes JSON report
- Prints summary for manual review

Manual step (required): spot-check 1-2 lines against the company's real website(s).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from market_research.config import load_settings, build_llm_client, get_brave_key
from market_research import storage as stg
from market_research.pipeline import ResearchContext, determine_product_lines


# Simplified: the PoC is for one configured company + subsidiaries only.
# We still run the verifier against the TARGET_COMPANY.

REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(exist_ok=True)


def main() -> int:
    settings = load_settings()
    client = build_llm_client(settings)
    ctx = ResearchContext(
        llm_client=client,
        model=settings.model,
        db_path=settings.db_path,
        brave_api_key=get_brave_key(settings),
        status_callback=print,
    )
    stg.init_db(ctx.db_path)

    target = settings.target_company
    print(f"\n=== Verifying product lines for configured target: {target} ===")

    results = []
    all_ok = True

    try:
        lines = determine_product_lines(ctx)
    except Exception as e:
        print(f"ERROR: {e}")
        results.append({"company": target, "error": str(e), "ok": False})
        all_ok = False

    if all_ok:
        n = len(lines)
        has_names = all(bool(l.get("name")) for l in lines)
        has_sources = any(l.get("sources") for l in lines)
        ok = n >= 2 and has_names and has_sources

        print(f"  Lines: {n} | Names ok: {has_names} | Sources present: {has_sources} | PASS: {ok}")

        results.append({
            "company": target,
            "num_lines": n,
            "lines": [{"name": l["name"], "description": l.get("description", "")[:120]} for l in lines],
            "has_sources": has_sources,
            "ok": ok,
        })
        if not ok:
            all_ok = False

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"verify_product_lines_{ts}.json"
    report = {
        "timestamp": ts,
        "model": settings.model,
        "db": settings.db_path,
        "brave_used": bool(get_brave_key(settings)),
        "target_company": settings.target_company,
        "results": results,
        "overall_pass": all_ok,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written: {report_path}")

    if all_ok:
        print("\n[OK] Basic gates passed for the configured company.")
        print("NEXT: Manually review the report + visit the company's site(s) to confirm major lines captured.")
        return 0
    else:
        print("\n[FAIL] Gates not met. Fix then re-run.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
