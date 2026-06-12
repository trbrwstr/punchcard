# Punchcard

**Modernization support for legacy COBOL systems — built for teams that need clarity before they change critical code.**

Punchcard is a COBOL analysis and review workbench designed to help organizations understand legacy programs, identify risky logic, and prepare safer modernization plans. It combines parser-backed source analysis with optional LLM-assisted explanations so teams can move from "we are afraid to touch this" to a clear, auditable review workflow.

If you found this project through Fiverr, Upwork, or my freelance portfolio, Punchcard represents the type of practical modernization tooling I can build, adapt, or extend for your business.

## What I can help you with

I work with clients who need dependable engineering support around legacy systems, automation, and modernization. Typical engagements include:

* **COBOL code review and inventory** — map programs, paragraphs, copybooks, file operations, external calls, and high-risk control flow.
* **Modernization planning** — turn undocumented legacy code into a phased migration roadmap with clear risks, dependencies, and delivery milestones.
* **Static analysis tools** — build custom analyzers, parsers, dashboards, and reports for proprietary source code.
* **LLM-assisted review workflows** — add guarded AI explanations, rewrite suggestions, and audit trails without blindly trusting model output.
* **Internal developer tools** — create CLIs, web apps, APIs, and automation scripts that reduce manual review time.
* **Secure integration work** — connect tools to internal systems while protecting sensitive source code and business data.

## Why Punchcard exists

Legacy code often runs business-critical operations, but many teams lack the original authors, documentation, or safe test coverage. Modernization efforts fail when teams start rewriting before they understand the system.

Punchcard is built around a safer process:

1. **Parse the source** into a structured representation.
2. **Preserve traceability** back to the original lines of code.
3. **Score risk and complexity** so reviewers know where to focus first.
4. **Review changes paragraph by paragraph** instead of attempting a risky big-bang rewrite.
5. **Export an audit trail** so decisions are visible and repeatable.

The goal is not to replace experienced engineers. The goal is to give them better tools.

## Current capabilities

Punchcard currently provides:

| Capability | Description |
| --- | --- |
| COBOL parsing | Reads COBOL source and builds a structured intermediate representation. |
| Copybook handling | Expands `COPY` statements from configured copybook paths. |
| Risk scoring | Flags patterns such as `GO TO`, `ALTER`, external `CALL`, file I/O, and `REDEFINES`. |
| Complexity estimates | Computes paragraph-level cyclomatic complexity to prioritize review. |
| Review workflow | Tracks paragraph status, translations, accept/reject decisions, and exportable results. |
| API access | Provides FastAPI endpoints for uploads, review status, translation, and export. |
| Web and terminal UIs | Supports both a browser interface and a terminal-based workflow. |
| Offline-safe default | Uses a local mock LLM client unless a real API key is explicitly configured. |

## Example client deliverables

Depending on your needs, I can turn this foundation into a client-ready deliverable such as:

* A COBOL inventory report for a specific application portfolio.
* A risk-ranked modernization assessment.
* A searchable web dashboard for legacy programs and copybooks.
* A secure internal review tool with role-based workflow.
* A custom parser or analyzer for your organization's coding standards.
* A migration planning document with MVP scope, milestones, and technical tradeoffs.
* A proof of concept that translates selected COBOL paragraphs into another language for human review.

## Engagement approach

I prefer small, useful milestones over vague large projects. A typical engagement looks like this:

1. **Discovery** — confirm goals, constraints, sample inputs, security requirements, and success criteria.
2. **Prototype** — build or adapt a narrow workflow against representative source files.
3. **Review** — validate output with your subject-matter experts and adjust assumptions.
4. **Production hardening** — add authentication, logging, deployment scripts, tests, and documentation as needed.
5. **Handoff** — deliver source code, setup instructions, usage documentation, and a clear next-step roadmap.

## Security and confidentiality

Legacy source code can contain sensitive business logic, credentials, data formats, and operational procedures. Punchcard is designed with a conservative default posture:

* No external LLM calls are made unless an API key is explicitly configured.
* Proprietary source should not be sent to third-party AI services without written approval.
* Client projects should define a redaction policy, retention policy, and audit process before using hosted AI models.
* Local/offline workflows are preferred when confidentiality requirements are strict.

## Technology snapshot

Punchcard is built with pragmatic, maintainable tools:

* **Python 3.12** for the backend and command-line tooling.
* **FastAPI** for the review API.
* **ANTLR-based COBOL parsing** for structured source analysis.
* **Textual** for the terminal interface.
* **React + Vite** for the web interface.
* **Pytest and Ruff** for testing and code quality.

## Running the project locally

Developers can run Punchcard locally with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync --dev
uv run pytest
uv run punchcard fixtures/hello.cbl
```

To start the terminal UI:

```bash
uv run punchcard-tui --source program.cbl
```

To build and serve the web UI:

```bash
cd frontend
npm install
npm run build
cd ..
uv run punchcard-web
```

## Project structure

| Path | Purpose |
| --- | --- |
| `punchcard/backend/parser/` | COBOL parsing, intermediate representation models, copybook handling, and complexity scoring. |
| `punchcard/backend/llm/` | Optional LLM translation client, prompt templates, and confidence scoring. |
| `punchcard/backend/review/` | Shared review service used by the API and terminal UI. |
| `punchcard/backend/api/` | FastAPI endpoints for upload, review, translation, and export. |
| `punchcard/tui/` | Terminal review interface. |
| `frontend/` | Browser-based review interface. |
| `fixtures/` | Small COBOL examples for repeatable parser and review tests. |
| `tests/` | Automated test suite. |

## Limitations

Punchcard is an active modernization workbench, not a magic one-click rewrite system. Important limitations include:

* COBOL dialects vary widely, so real client code may require parser tuning.
* Data declarations are retained for review but are not yet modeled as a full typed data-flow graph.
* Control-flow analysis is useful but not a substitute for domain expert validation.
* AI-generated explanations or rewrites must be reviewed by humans before use.
* Production deployments should add client-specific authentication, authorization, logging, and data-retention controls.

## Interested in working together?

If you need help understanding, modernizing, or safely automating around legacy systems, I can help turn your source code and operational goals into a practical plan.

Useful starting points for a first message:

* What language or system do you need reviewed?
* How many programs, files, or lines of code are involved?
* Are there copybooks, JCL, database schemas, or external integrations?
* Do you need a report, a working tool, a migration plan, or implementation support?
* Are there confidentiality or offline-only requirements?

I can start with a focused assessment and then scale into tooling, automation, or modernization support once the highest-value path is clear.
