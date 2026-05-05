"""CLI entrypoint. `asp <command>` is the user-facing surface."""

from __future__ import annotations

import typer

from asp_cli.commands import ontology

app = typer.Typer(
    name="asp",
    help="Agentic Security Platform CLI",
    no_args_is_help=True,
    add_completion=False,
)

app.add_typer(ontology.app, name="ontology")


@app.command()
def version() -> None:
    """Print asp-cli version."""
    from asp_cli import __version__

    typer.echo(__version__)


if __name__ == "__main__":
    app()
