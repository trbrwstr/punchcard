"""Command-line and FastAPI entry points for Punchcard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from rich.console import Console

from punchcard.backend.api.routes import init_db
from punchcard.backend.api.routes import router as api_router
from punchcard.backend.parser.cobol_listener import parse_cobol

console = Console()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize API resources when the web app starts."""

    init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure the Punchcard FastAPI application."""

    app = FastAPI(title="Punchcard API", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)
    return app


app = create_app()


def main() -> None:
    """Parse an optional COBOL file and print a tiny summary."""

    import argparse

    parser = argparse.ArgumentParser(description="Parse a COBOL file into Punchcard IR.")
    parser.add_argument("path", nargs="?", type=Path, help="COBOL source file to parse")
    args = parser.parse_args()

    if args.path is None:
        console.print("Punchcard is ready. Pass a COBOL file path to parse it.")
        return

    program = parse_cobol(args.path.read_text(encoding="utf-8"))
    console.print(
        {
            "program_id": program.program_id,
            "statements": len(program.all_statements),
        }
    )


if __name__ == "__main__":
    main()
