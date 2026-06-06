"""Minimal keyboard-driven Textual UI for rewrite review sessions."""

from __future__ import annotations

import argparse
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, VerticalScroll
from textual.widgets import Footer, Header, Static, TextArea

from punchcard.backend.review import RewriteSession, RewriteSessionService, session_service


class PunchcardTui(App[None]):
    """Review COBOL rewrite suggestions from a shared backend session."""

    CSS = """
    Grid {
        grid-size: 2 3;
        grid-gutter: 1;
        padding: 1;
    }

    .panel {
        border: solid $accent;
        padding: 1;
        height: 1fr;
    }

    #suggestion {
        border: solid $success;
        height: 1fr;
    }

    #diff {
        column-span: 2;
    }

    #status {
        column-span: 2;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("a", "accept", "Accept", key_display="A"),
        Binding("e", "edit", "Edit", key_display="E"),
        Binding("r", "reject", "Reject/regenerate", key_display="R"),
        Binding("s", "skip", "Skip", key_display="S"),
        Binding("q", "quit", "Quit", key_display="Q"),
    ]

    def __init__(self, session: RewriteSession, service: RewriteSessionService | None = None) -> None:
        super().__init__()
        self.session = session
        self.service = service or session_service

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Grid():
            with VerticalScroll(classes="panel"):
                yield Static("", id="original")
            yield TextArea("", id="suggestion", language="python")
            with VerticalScroll(classes="panel", id="diff"):
                yield Static("", id="diff_text")
            yield Static("", id="status", classes="panel")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Punchcard Rewrite Review"
        self.sub_title = self.session.id
        self._refresh_item()

    def action_accept(self) -> None:
        """Accept the current proposal, including any edited text."""

        suggestion = self.query_one("#suggestion", TextArea).text
        self.service.accept(self.session.id, edited_translation=suggestion)
        self._refresh_item()

    def action_edit(self) -> None:
        """Focus the suggestion editor so the reviewer can change text."""

        self.query_one("#suggestion", TextArea).focus()
        self.notify("Editing suggestion. Press A to accept the edited text.", title="Edit mode")

    def action_reject(self) -> None:
        """Reject the current proposal and ask the service for a regeneration."""

        self.service.reject_and_regenerate(self.session.id)
        self._refresh_item()

    def action_skip(self) -> None:
        """Skip the current proposal."""

        self.service.skip(self.session.id)
        self._refresh_item()

    def _refresh_item(self) -> None:
        item = self.service.current_item(self.session.id)
        original = self.query_one("#original", Static)
        suggestion = self.query_one("#suggestion", TextArea)
        diff_text = self.query_one("#diff_text", Static)
        status = self.query_one("#status", Static)

        if item is None:
            original.update("Review complete. Yasher koach — the queue is empty.")
            suggestion.text = ""
            diff_text.update("")
            status.update("No pending items. Press Q to quit.")
            return

        risks = ", ".join(item.risk_flags) if item.risk_flags else "none"
        original.update(f"Original COBOL paragraph: {item.paragraph_name}\n\n{item.original}")
        suggestion.text = item.suggested_translation
        diff_text.update(f"Unified diff\n\n{item.unified_diff}")
        status.update(
            " | ".join(
                [
                    f"Confidence: {item.confidence_score:.0%}",
                    f"Risk flags: {risks}",
                    "Keys: A accept, E edit, R reject/regenerate, S skip, Q quit",
                ]
            )
        )


def build_session(args: argparse.Namespace, service: RewriteSessionService | None = None) -> RewriteSession:
    """Load or connect to a rewrite session for the TUI entry point."""

    active_service = service or session_service
    if args.session_id:
        return active_service.get(args.session_id)
    if args.session:
        return active_service.load_json(args.session)
    if args.source:
        return active_service.create_from_cobol(args.source.read_text(encoding="utf-8"))
    raise SystemExit("Provide --source PATH, --session PATH, or --session-id ID.")


def main() -> None:
    """Start the minimal Punchcard terminal UI."""

    parser = argparse.ArgumentParser(description="Review COBOL rewrite suggestions in a keyboard-driven TUI.")
    parser.add_argument("--source", type=Path, help="COBOL source file used to create a new rewrite session")
    parser.add_argument("--session", type=Path, help="JSON session file to load")
    parser.add_argument("--session-id", help="Existing in-process session id to connect to")
    args = parser.parse_args()

    session = build_session(args)
    PunchcardTui(session).run()


if __name__ == "__main__":
    main()
