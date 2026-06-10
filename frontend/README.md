# Punchcard web UI

A React + Vite single-page app for the human-in-the-loop COBOL review workflow:
upload a source file, pick a target language, then translate / accept / reject
each paragraph and download the assembled result. It talks to the FastAPI
backend in `punchcard/backend/`.

## Develop

Run the backend and the Vite dev server side by side (the dev server proxies
`/sessions` calls to `http://localhost:8000`):

```bash
# terminal 1 — API
uv run uvicorn punchcard.backend.main:app --reload

# terminal 2 — UI with hot reload
cd frontend
npm install
npm run dev
```

## Build & serve

```bash
cd frontend
npm run build        # outputs frontend/dist
uv run punchcard-web # FastAPI serves dist/ + the API at http://127.0.0.1:8000
```

`punchcard-web` serves the built UI when `frontend/dist` exists, and the API
alone otherwise.

## Checks

```bash
npm run typecheck    # tsc -b
npm run build        # production build
npm run lint         # eslint
```
