"""Basic Streamlit UI for Market Research PoC (product lines v0.1).

Run: streamlit run app.py

Pattern inspired by AIE bigbot/app/ui.py (session_state + rerun for steps).
"""

from __future__ import annotations

import streamlit as st

from market_research.config import load_settings, build_llm_client, get_brave_key
from market_research import storage as stg
from market_research.pipeline import ResearchContext, determine_product_lines


st.set_page_config(page_title="Market Research PoC", layout="wide")
st.title("Market Research PoC — Product Lines (v0.3)")

st.caption("Simplified PoC for ONE company + its subsidiaries. Research refreshes data (no dups). Configure via TARGET_COMPANY in .env. Use CLI 'clean' if needed. v0.3: per-entity product line extraction (main + each sub separately) for correct attribution instead of LLM guessing from mixed content.")

# Session state
if "lines" not in st.session_state:
    st.session_state.lines = []
if "subsidiaries" not in st.session_state:
    st.session_state.subsidiaries = []
if "status_log" not in st.session_state:
    st.session_state.status_log = []
if "loaded_from_db" not in st.session_state:
    st.session_state.loaded_from_db = False

settings = load_settings()
stg.init_db(settings.db_path)
target_company = settings.target_company

# On app start (fresh session_state), auto-populate product lines + subsidiaries from the database
# for the configured company. This way previous research (CLI or prior runs) is visible immediately.
if not st.session_state.loaded_from_db:
    row = stg.get_company_by_name(target_company, settings.db_path)
    if row:
        cid, _, _ = row
        st.session_state.lines = stg.list_product_lines_with_sources(cid, settings.db_path)
        st.session_state.subsidiaries = stg.list_subsidiaries(cid, settings.db_path)
    else:
        st.session_state.lines = []
        st.session_state.subsidiaries = []
    st.session_state.status_log = []  # start with clean log on initial DB load
    st.session_state.loaded_from_db = True

# Top command buttons in one row
btn_col1, btn_col2, btn_col3 = st.columns(3)
with btn_col1:
    research_btn = st.button("🔍 Research Product Lines", type="primary", use_container_width=True)
with btn_col2:
    reload_btn = st.button("🔄 Reload from DB", use_container_width=True)
with btn_col3:
    clear_btn = st.button("🗑️ Clear Results", use_container_width=True)

# Handle clear and reload at top level (they cause rerun)
if clear_btn:
    st.session_state.lines = []
    st.session_state.subsidiaries = []
    st.session_state.status_log = []
    st.rerun()

if reload_btn:
    row = stg.get_company_by_name(target_company, settings.db_path)
    if row:
        cid, _, _ = row
        st.session_state.lines = stg.list_product_lines_with_sources(cid, settings.db_path)
        st.session_state.subsidiaries = stg.list_subsidiaries(cid, settings.db_path)
    else:
        st.session_state.lines = []
        st.session_state.subsidiaries = []
    st.session_state.status_log = []
    st.rerun()

# Heavy research logic (triggered from top button)
if research_btn:
    st.session_state.status_log = []
    st.session_state.lines = []
    st.session_state.subsidiaries = []

    def status(msg: str):
        st.session_state.status_log.append(msg)

    client = build_llm_client(settings)
    ctx = ResearchContext(
        llm_client=client,
        model=settings.model,
        status_callback=status,
        db_path=settings.db_path,
        brave_api_key=get_brave_key(settings),
    )

    with st.status(f"Researching product lines for {target_company}...", expanded=True) as status_box:
        for msg in st.session_state.status_log:
            st.write(msg)
        lines = determine_product_lines(ctx)
        st.session_state.lines = lines
        # Refresh subsidiaries list from DB (research may have updated them)
        row = stg.get_company_by_name(target_company, settings.db_path)
        if row:
            cid, _, _ = row
            st.session_state.subsidiaries = stg.list_subsidiaries(cid, settings.db_path)
        else:
            st.session_state.subsidiaries = []
        status_box.update(label=f"Done — {len(lines)} lines", state="complete")

    # Re-run to refresh the full interface (buttons stay at top, lists update from DB)
    st.rerun()

# --- Main UI content: buttons at top (one row), subsidiaries LEFT, product lines RIGHT ---

# Two-column layout for content
left_col, right_col = st.columns([1, 2])  # left for subsidiaries, right for product lines

with left_col:
    st.markdown(f"**Target Company:** {target_company}")
    st.caption("(configured in .env as TARGET_COMPANY + its subsidiaries)")

    # Subsidiaries list - always fresh from DB, names are clickable links to website
    row = stg.get_company_by_name(target_company, settings.db_path)
    subs_list = []
    if row:
        cid, _, _ = row
        subs_list = stg.list_subsidiaries(cid, settings.db_path)
        st.session_state.subsidiaries = subs_list

    if subs_list:
        st.markdown("**Subsidiaries / Divisions**")
        for sub in subs_list:
            name = sub.get("name", "")
            web = sub.get("website", "")
            area = sub.get("business_area", "")
            extra = f" — {area}" if area else ""
            if web:
                # Name itself is the clickable link to the website
                st.markdown(f"- **[{name}]({web})**{extra}")
            else:
                st.markdown(f"- **{name}**{extra}")
    else:
        st.caption("No subsidiaries discovered yet.")

    # Compact settings in left column
    with st.expander("⚙️ Settings"):
        st.code(
            f"Model: {settings.model}\n"
            f"DB: {settings.db_path}\n"
            f"Brave key: {'set' if get_brave_key(settings) else 'not set (using DDG fallback)'}\n"
            f"LLM base: {settings.openai_base_url}"
        )

with right_col:
    # Product lines display (right side)
    if st.session_state.lines:
        st.subheader(f"Product Lines for {target_company} (incl. subsidiaries)")
        for ln in st.session_state.lines:
            sub = ln.get("subsidiary") or "Main Company"
            title = f"**{ln['name']}**" + (f" — *{sub}*" if sub != "Main Company" else "")
            with st.expander(title, expanded=False):  # start closed
                st.write(ln.get("description", ""))
                if ln.get("key_examples"):
                    st.markdown("**Examples:** " + ln["key_examples"])

                # Show subsidiary + website link in the details
                if sub and sub != "Main Company":
                    sub_web = ""
                    for s in st.session_state.get("subsidiaries", []):
                        if s.get("name", "").lower() == sub.lower():
                            sub_web = s.get("website", "")
                            break
                    if sub_web:
                        st.markdown(f"**Subsidiary:** [{sub}]({sub_web})")
                    else:
                        st.markdown(f"**Subsidiary:** {sub}")

                srcs = ln.get("sources", [])
                if srcs:
                    st.markdown("**Sources / Evidence:**")
                    for s in srcs[:4]:
                        url = s.get("url", "")
                        st.markdown(f"- [{url}]({url})" if url else f"- {s}")
                else:
                    st.caption("(no sources)")
    else:
        st.info(
            f"No product lines stored in the database for **{target_company}** yet.\n\n"
            "Click the **Research Product Lines** button above, "
            "or run `python -m market_research.cli research` from the terminal."
        )

# Research log at bottom (full width)
if st.session_state.status_log:
    with st.expander("Research log (last run)"):
        for m in st.session_state.status_log:
            st.text(m)

st.divider()
st.caption("CLI is the primary dev/verify interface. This is a convenience UI. Data lives in the SQLite DB. v0.3")
