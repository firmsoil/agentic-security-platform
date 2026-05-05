"""`asp ontology ...` subcommands."""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from asp_core.graph import load_ontology

app = typer.Typer(help="Inspect and validate the graph ontology.", no_args_is_help=True)
console = Console()


@app.command("show")
def show(version: str = typer.Option("v1", help="Ontology version")) -> None:
    """Print the ontology as JSON."""
    ontology = load_ontology(version)
    typer.echo(ontology.model_dump_json(indent=2))


@app.command("validate")
def validate(version: str = typer.Option("v1", help="Ontology version")) -> None:
    """Validate that the bundled ontology loads and has required content."""
    ontology = load_ontology(version)

    problems: list[str] = []
    if len(ontology.nodes) == 0:
        problems.append("no node types defined")
    if len(ontology.edges) == 0:
        problems.append("no edge types defined")

    node_names = [n.name for n in ontology.nodes]
    if len(node_names) != len(set(node_names)):
        problems.append("duplicate node type names")
    edge_names = [e.name for e in ontology.edges]
    if len(edge_names) != len(set(edge_names)):
        problems.append("duplicate edge type names")

    # AI-differentiator check.
    required_ai_edges = {
        "PROMPT_INJECTABLE_INTO",
        "TOOL_INVOKABLE_BY",
        "MEMORY_POISONABLE_BY",
    }
    missing = required_ai_edges - set(edge_names)
    if missing:
        problems.append(f"missing required AI edges: {sorted(missing)}")

    if problems:
        console.print("[red]Ontology validation FAILED[/red]")
        for p in problems:
            console.print(f"  - {p}")
        raise typer.Exit(code=1)

    console.print(f"[green]Ontology {ontology.version} OK[/green]")
    console.print(f"  nodes: {len(ontology.nodes)}")
    console.print(f"  edges: {len(ontology.edges)}")


@app.command("summary")
def summary(version: str = typer.Option("v1", help="Ontology version")) -> None:
    """Print a table summarizing node/edge counts by category."""
    ontology = load_ontology(version)

    node_table = Table(title=f"Node types ({ontology.version})")
    node_table.add_column("Category")
    node_table.add_column("Count", justify="right")
    node_table.add_column("Names")
    from collections import defaultdict

    by_cat: dict[str, list[str]] = defaultdict(list)
    for n in ontology.nodes:
        by_cat[n.category.value].append(n.name)
    for cat, names in sorted(by_cat.items()):
        node_table.add_row(cat, str(len(names)), ", ".join(sorted(names)))
    console.print(node_table)

    edge_table = Table(title=f"Edge types ({ontology.version})")
    edge_table.add_column("Category")
    edge_table.add_column("Count", justify="right")
    edge_table.add_column("Names")
    by_cat_e: dict[str, list[str]] = defaultdict(list)
    for e in ontology.edges:
        by_cat_e[e.category.value].append(e.name)
    for cat, names in sorted(by_cat_e.items()):
        edge_table.add_row(cat, str(len(names)), ", ".join(sorted(names)))
    console.print(edge_table)


@app.command("mappings")
def mappings(
    framework: str = typer.Option(None, help="Filter to a single framework"),
    version: str = typer.Option("v1", help="Ontology version"),
) -> None:
    """List framework mappings attached to ontology elements."""
    ontology = load_ontology(version)
    out: list[dict[str, str]] = []
    for n in ontology.nodes:
        for m in n.mappings:
            if framework and m.framework != framework:
                continue
            out.append(
                {
                    "kind": "node",
                    "name": n.name,
                    "framework": m.framework,
                    "identifier": m.identifier,
                    "title": m.title or "",
                }
            )
    for e in ontology.edges:
        for m in e.mappings:
            if framework and m.framework != framework:
                continue
            out.append(
                {
                    "kind": "edge",
                    "name": e.name,
                    "framework": m.framework,
                    "identifier": m.identifier,
                    "title": m.title or "",
                }
            )
    typer.echo(json.dumps(out, indent=2))
