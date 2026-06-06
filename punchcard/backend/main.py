"""Command-line entry point for Punchcard."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from punchcard.backend.parser.cobol_listener import parse_cobol

console = Console()


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
