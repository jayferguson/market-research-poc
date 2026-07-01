"""CLI for Market Research PoC (v0.1 product lines).

Primary interface for rapid iteration and verification.
Uses rich for tables and progress.

Run: python -m market_research.cli research "Company Name"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from .config import load_settings, build_llm_client, get_brave_key
from . import storage as st
from .pipeline import ResearchContext, determine_product_lines


app = typer.Typer(help="Market Research PoC - product lines (v0.1) and beyond")
console = Console()


def _ctx_from_settings() -> ResearchContext:
    s = load_settings()
    client = build_llm_client(s)
    return ResearchContext(
        llm_client=client,
        model=s.model,
        db_path=s.db_path,
        brave_api_key=get_brave_key(s),
    )


@app.command()
def research(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override LLM model"),
    db: str = typer.Option("market_research.db", "--db", help="SQLite path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show extra status"),
):
    """Research product lines for the configured company (TARGET_COMPANY in .env) + its subsidiaries.
    Persists to DB + prints table. Re-runs refresh the data (no duplicates).
    """
    settings = load_settings()
    if model:
        settings.model = model
    if db:
        settings.db_path = db

    client = build_llm_client(settings)
    ctx = ResearchContext(
        llm_client=client,
        model=settings.model,
        db_path=settings.db_path,
        brave_api_key=get_brave_key(settings),
        status_callback=lambda m: console.print(f"[dim]{m}[/dim]") if verbose else None,
    )

    st.init_db(ctx.db_path)
    target = settings.target_company

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Researching product lines for {target} (and subsidiaries)...", total=None)
        lines = determine_product_lines(ctx)
        progress.update(task, description=f"Done — {len(lines)} lines found.")

    if not lines:
        console.print("[yellow]No product lines extracted. Check API keys / Brave key.[/yellow]")
        raise typer.Exit(code=1)

    _print_lines_table(target, lines)
    console.print(f"\n[green]Persisted to {ctx.db_path}. Use 'show' to inspect.[/green]")


def _print_lines_table(company: str, lines: list[dict]):
    table = Table(title=f"Product Lines — {company}", show_lines=True)
    table.add_column("Line", style="cyan", no_wrap=True)
    table.add_column("Subsidiary / Source", style="yellow")
    table.add_column("Description", style="white")
    table.add_column("Evidence / Sources", style="dim")

    for ln in lines:
        ev = ln.get("sources", []) or []
        ev_text = "\n".join([f"- {e.get('url','')}" for e in ev[:3]]) or "(no sources recorded)"
        sub = ln.get("subsidiary") or "Main Company"
        table.add_row(
            ln["name"],
            sub,
            (ln.get("description") or "")[:180],
            ev_text[:280],
        )
    console.print(table)


# 'list' command removed in simplification: this PoC is for one configured company + subsidiaries only.
# Use 'show' instead.


@app.command()
def show():
    """Show stored product lines + sources for the configured company (and subsidiaries)."""
    s = load_settings()
    st.init_db(s.db_path)
    target = s.target_company
    row = st.get_company_by_name(target, s.db_path)
    if not row:
        console.print(f"[red]No data for '{target}' yet. Run 'research' first.[/red]")
        raise typer.Exit(1)
    cid, name, website = row
    lines = st.list_product_lines_with_sources(cid, s.db_path)
    if not lines:
        console.print("No product lines stored.")
    else:
        _print_lines_table(name, lines)

    subs = st.list_subsidiaries(cid, s.db_path)
    if subs:
        console.print("\nSubsidiaries / Divisions:")
        for sub in subs:
            web = sub.get("website", "")
            area = sub.get("business_area", "")
            line = f"- {sub['name']}"
            if web:
                line += f" — {web}"
            if area:
                line += f" ({area})"
            console.print(line)
    else:
        console.print("\nNo subsidiaries stored.")

    console.print(f"\nDB: {s.db_path} | Website: {website}")


@app.command()
def clean():
    """Clear (delete) all previously stored product lines + sources for the configured company.
    Use this to reset before re-researching.
    """
    s = load_settings()
    st.init_db(s.db_path)
    target = s.target_company
    row = st.get_company_by_name(target, s.db_path)
    if not row:
        console.print(f"[yellow]No existing data for '{target}'.[/yellow]")
        return
    st.clear_product_lines_for_company(row[0], s.db_path)
    console.print(f"[green]Cleared product lines for {row[1]}.[/green]")
    console.print("You can now safely re-run 'research' for a clean result.")


if __name__ == "__main__":
    app()
