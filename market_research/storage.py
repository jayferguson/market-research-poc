"""SQLite storage for market research PoC (v0.1 product lines focus).

Simple raw sqlite3 (inspired by SalesCrossSell db.py + small PoC patterns).
Tables support company + product lines + citation sources.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any


DB_PATH_DEFAULT = "market_research.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    website TEXT,
    last_researched TEXT
);
CREATE TABLE IF NOT EXISTS product_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    key_examples TEXT,
    target_verticals_hint TEXT,
    subsidiary TEXT,                 -- NULL = main company; name of subsidiary/brand/division otherwise
    FOREIGN KEY(company_id) REFERENCES companies(id)
);
CREATE TABLE IF NOT EXISTS line_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_line_id INTEGER NOT NULL,
    url TEXT,
    title TEXT,
    query_used TEXT,
    snippet TEXT,
    fetched_at TEXT,
    FOREIGN KEY(product_line_id) REFERENCES product_lines(id)
);
CREATE INDEX IF NOT EXISTS idx_lines_company ON product_lines(company_id);
CREATE INDEX IF NOT EXISTS idx_sources_line ON line_sources(product_line_id);

-- Prevent exact name duplicates per company (case-insensitive via expression index)
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_line_name ON product_lines(company_id, LOWER(name));

CREATE TABLE IF NOT EXISTS subsidiaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    website TEXT,
    business_area TEXT,
    FOREIGN KEY(company_id) REFERENCES companies(id)
);
CREATE INDEX IF NOT EXISTS idx_subs_company ON subsidiaries(company_id);
"""


def init_db(db_path: str = DB_PATH_DEFAULT) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    except Exception:
        # Index creation may fail if duplicate names already exist from earlier runs.
        # That's fine; the application-level dedup + clear logic will handle future inserts.
        pass

    # Best-effort: add the subsidiary column if the DB is from before the simplification
    try:
        conn.execute("ALTER TABLE product_lines ADD COLUMN subsidiary TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists or table not there yet

    # Best-effort: create subsidiaries table for older DBs
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subsidiaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                website TEXT,
                business_area TEXT,
                FOREIGN KEY(company_id) REFERENCES companies(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_subs_company ON subsidiaries(company_id)")
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _connect(db_path: str):
    return sqlite3.connect(db_path)


def upsert_company(name: str, website: str = "", db_path: str = DB_PATH_DEFAULT) -> int:
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO companies (name, website) VALUES (?, ?)", (name, website))
        c.execute("SELECT id FROM companies WHERE name = ?", (name,))
        cid = c.fetchone()[0]
        c.execute(
            "UPDATE companies SET website = COALESCE(?, website), last_researched = ? WHERE id = ?",
            (website or None, datetime.now().isoformat(), cid),
        )
        conn.commit()
        return cid
    finally:
        conn.close()


def insert_product_line(
    company_id: int,
    name: str,
    description: str = "",
    key_examples: str | list[str] = "",
    target_verticals_hint: str = "",
    subsidiary: str | None = None,
    db_path: str = DB_PATH_DEFAULT,
    skip_if_exists: bool = True,
) -> int:
    """Insert a product line. If skip_if_exists=True (default), avoids duplicate names (case-insensitive).
    subsidiary: None for main company, otherwise the sub/brand name.
    """
    norm = (name or "").lower().strip()
    if skip_if_exists:
        existing = get_existing_line_names(company_id, db_path)
        if norm in existing:
            return -1  # indicate skipped

    conn = _connect(db_path)
    try:
        c = conn.cursor()
        if isinstance(key_examples, list):
            key_examples = ", ".join(key_examples)
        c.execute(
            """INSERT INTO product_lines (company_id, name, description, key_examples, target_verticals_hint, subsidiary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company_id, name, description, key_examples or "", target_verticals_hint or "", subsidiary),
        )
        conn.commit()
        return c.lastrowid
    finally:
        conn.close()


def insert_line_source(
    product_line_id: int,
    url: str = "",
    title: str = "",
    query_used: str = "",
    snippet: str = "",
    db_path: str = DB_PATH_DEFAULT,
) -> None:
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            """INSERT INTO line_sources (product_line_id, url, title, query_used, snippet, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (product_line_id, url, title, query_used, snippet[:500], datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def list_product_lines_with_sources(
    company_id: int, db_path: str = DB_PATH_DEFAULT
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            """SELECT p.id, p.name, p.description, p.key_examples, p.target_verticals_hint, p.subsidiary,
                      s.url, s.title, s.snippet, s.query_used
               FROM product_lines p
               LEFT JOIN line_sources s ON s.product_line_id = p.id
               WHERE p.company_id = ?
               ORDER BY COALESCE(p.subsidiary, ''), p.name, s.id""",
            (company_id,),
        )
        rows = c.fetchall()
        lines: dict[int, dict] = {}
        for r in rows:
            lid = r[0]
            if lid not in lines:
                lines[lid] = {
                    "id": lid,
                    "name": r[1],
                    "description": r[2] or "",
                    "key_examples": r[3] or "",
                    "target_verticals_hint": r[4] or "",
                    "subsidiary": r[5],  # None or name of sub/division
                    "sources": [],
                }
            if r[6]:
                lines[lid]["sources"].append(
                    {"url": r[6], "title": r[7] or "", "snippet": r[8] or "", "query": r[9] or ""}
                )
        return list(lines.values())
    finally:
        conn.close()


def get_company_by_name(name: str, db_path: str = DB_PATH_DEFAULT) -> tuple[int, str, str] | None:
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, website FROM companies WHERE name = ?", (name,))
        row = c.fetchone()
        return (row[0], row[1], row[2] or "") if row else None
    finally:
        conn.close()


def clear_product_lines_for_company(company_id: int, db_path: str = DB_PATH_DEFAULT) -> None:
    """Delete all existing product lines and their sources for a company.
    Used on re-research to keep a clean 'current view' instead of accumulating duplicates.
    """
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM line_sources WHERE product_line_id IN (SELECT id FROM product_lines WHERE company_id = ?)",
            (company_id,)
        )
        c.execute("DELETE FROM product_lines WHERE company_id = ?", (company_id,))
        conn.commit()
    finally:
        conn.close()


def get_existing_line_names(company_id: int, db_path: str = DB_PATH_DEFAULT) -> set[str]:
    """Return set of normalized (lower) line names already stored for the company."""
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute("SELECT name FROM product_lines WHERE company_id = ?", (company_id,))
        return {row[0].lower().strip() for row in c.fetchall() if row[0]}
    finally:
        conn.close()


def upsert_subsidiary(
    company_id: int,
    name: str,
    website: str = "",
    business_area: str = "",
    db_path: str = DB_PATH_DEFAULT,
) -> int:
    """Create-or-update a subsidiary row."""
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO subsidiaries (company_id, name, website, business_area) VALUES (?, ?, ?, ?)",
            (company_id, name, website, business_area),
        )
        c.execute(
            "SELECT id FROM subsidiaries WHERE company_id = ? AND name = ?",
            (company_id, name),
        )
        row = c.fetchone()
        if row:
            sub_id = row[0]
            c.execute(
                "UPDATE subsidiaries SET website = ?, business_area = ? WHERE id = ?",
                (website or None, business_area or None, sub_id),
            )
            conn.commit()
            return sub_id
        return -1
    finally:
        conn.close()


def list_subsidiaries(company_id: int, db_path: str = DB_PATH_DEFAULT) -> list[dict]:
    """Return list of subsidiaries for the company with name, website, business_area."""
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT name, website, business_area FROM subsidiaries WHERE company_id = ? ORDER BY name",
            (company_id,),
        )
        return [
            {"name": r[0], "website": r[1] or "", "business_area": r[2] or ""}
            for r in c.fetchall()
        ]
    finally:
        conn.close()


def clear_subsidiaries_for_company(company_id: int, db_path: str = DB_PATH_DEFAULT) -> None:
    """Delete subsidiaries for the company (called on re-research for freshness)."""
    conn = _connect(db_path)
    try:
        c = conn.cursor()
        c.execute("DELETE FROM subsidiaries WHERE company_id = ?", (company_id,))
        conn.commit()
    finally:
        conn.close()
