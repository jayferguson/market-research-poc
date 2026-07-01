"""LLM call helper + robust JSON extraction.

Adapted from SalesCrossSell/python_app/salescrosssell/llm.py
(for market-research-poc product-lines slice; kept independent).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI


LLM_PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "grok-4.3": {"input": 1.25 / 1_000_000, "output": 2.50 / 1_000_000},
    "grok-4.3-latest": {"input": 1.25 / 1_000_000, "output": 2.50 / 1_000_000},
    "grok-build-0.1": {"input": 1.00 / 1_000_000, "output": 2.00 / 1_000_000},
}


def _extract_json(text: str) -> Any:
    """Robustly pull JSON object/array from LLM output (markdown, extra text, minor syntax)."""
    if not text:
        return None
    text = text.strip()
    # strip ```json ... ```
    if "```" in text:
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if m:
            text = m.group(1).strip()
    # outermost array or object (prefer array when the text contains a top-level list)
    candidates = []
    # Try array first if [ appears before any {
    if "[" in text and (text.find("[") < text.find("{") or "{" not in text):
        candidates.append(("[", "]"))
    candidates.append(("{", "}"))
    candidates.append(("[", "]"))

    for opener, closer in candidates:
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            cand = text[start : end + 1]
            try:
                val = json.loads(cand)
                # If caller gave array-looking input and we got a dict, keep looking
                if isinstance(val, list) or opener == "[":
                    return val
                if "{" not in text[start+1:]:
                    return val
                # otherwise continue to try array
            except json.JSONDecodeError:
                cand = re.sub(r",\s*([}\]])", r"\1", cand)
                try:
                    val = json.loads(cand)
                    if isinstance(val, list):
                        return val
                    return val
                except Exception:
                    pass
    return None


def llm_analyze(
    prompt: str,
    system: str = "You are a precise market research assistant. Return only clean structured output when asked.",
    client: OpenAI | None = None,
    model: str | None = None,
    max_tokens: int = 2500,
    **kwargs,
) -> tuple[str, dict[str, Any]]:
    """Chat completion + (text, usage_dict). On error returns error text + zero usage.
    Extra kwargs (e.g. temperature=0.2) are forwarded to the completions.create call.
    """
    if client is None:
        # last resort - caller should pass configured client
        client = OpenAI(api_key=os.getenv("XAI_API_KEY") or "not-needed", base_url="https://api.x.ai/v1")
    if model is None:
        model = os.getenv("MODEL", "grok-4.3-latest")
    try:
        create_kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        create_kwargs.update(kwargs)  # e.g. temperature
        resp = client.chat.completions.create(**create_kwargs)
        text = (resp.choices[0].message.content or "").strip()
        usage = resp.usage
        rates = LLM_PRICING_PER_1M_TOKENS.get(model, {"input": 0, "output": 0})
        cost = (usage.prompt_tokens * rates["input"]) + (usage.completion_tokens * rates["output"])
        ud = {
            "model": model,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "cost": round(cost, 6),
        }
        return text, ud
    except Exception as e:
        return f"LLM error: {e}", {
            "model": model or "unknown",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
        }
