"""Command-line and FastAPI entry points for Punchcard."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from rich.console import Console

from punchcard.backend.api.routes import init_db
from punchcard.backend.api.routes import router as api_router
from punchcard.backend.parser.cobol_listener import parse_cobol

console = Console()

#: Built web UI (frontend/dist), served when present. Repo root is three levels up.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize API resources when the web app starts."""

    init_db()
    yield


def create_app() -> FastAPI:
    """Create and configure the Punchcard FastAPI application.

    The JSON API is always mounted. If the web UI has been built
    (``frontend/dist``), it is served as a single-page app at ``/`` — added last
    so the API routes take precedence.
    """

    app = FastAPI(title="Punchcard API", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)
    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="web")
    return app


app = create_app()


def serve() -> None:
    """Run the Punchcard web app (JSON API + built UI) with uvicorn."""

    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Serve the Punchcard web UI and API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not FRONTEND_DIST.is_dir():
        console.print(
            "[yellow]frontend/dist not found — serving the API only. "
            "Build the UI with 'npm run build' in frontend/.[/]"
        )
    console.print(f"Punchcard web on http://{args.host}:{args.port}")
    uvicorn.run("punchcard.backend.main:app", host=args.host, port=args.port)


def main() -> None:
    """Parse an optional COBOL file and print a tiny summary."""

    import argparse

    parser = argparse.ArgumentParser(description="Parse a COBOL file into Punchcard IR.")
    parser.add_argument("path", nargs="?", type=Path, help="COBOL source file to parse")
    parser.add_argument(
        "--copybook-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to search for COPY copybooks (repeatable)",
    )
    args = parser.parse_args()

    if args.path is None:
        console.print("Punchcard is ready. Pass a COBOL file path to parse it.")
        return

    program = parse_cobol(args.path.read_text(encoding="utf-8"), copybook_paths=args.copybook_path)
    console.print(
        {
            "program_id": program.program_id,
            "statements": len(program.all_statements),
        }
    )


if __name__ == "__main__":
    main()
