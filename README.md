# SmoothTalker

SmoothTalker is a role-aware AI reply assistant built around a Flutter desktop client and a FastAPI backend. It takes copied incoming text, uses thread memory plus retrieved reply examples, and returns three concise replies that are ready to send.

## What it does

- Generates replies for two roles: `crush` and `colleague`
- Uses a FastAPI + LangChain backend with Qwen through a DashScope OpenAI-compatible API
- Stores short-term thread memory separately from vector-retrieved reply examples
- Rewrites ambiguous retrieval queries with a structured LLM pass before vector search, with deterministic fallback
- Persists reply sessions and learns from the option the user actually copies
- Includes a primary Flutter desktop client and a lightweight web demo client

## Current status

- `flutter/` is the primary supported client
- The current Flutter implementation is primarily supported on Windows desktop
- `web/` is a minimal demo client
- PostgreSQL + `pgvector` is required for the current retrieval flow

## Screenshots

<table>
  <tr>
    <td align="center">
      <img src="UI%20Designs/Crush_1.png" alt="Crush role UI" width="360" />
    </td>
    <td align="center">
      <img src="UI%20Designs/Colleague_1.png" alt="Colleague role UI" width="360" />
    </td>
  </tr>
  <tr>
    <td align="center">Crush role</td>
    <td align="center">Colleague role</td>
  </tr>
  <tr>
    <td align="center">
      <img src="UI%20Designs/Crush_2.png" alt="Crush reply options" width="360" />
    </td>
    <td align="center">
      <img src="UI%20Designs/Colleague_2.png" alt="Colleague reply options" width="360" />
    </td>
  </tr>
  <tr>
    <td align="center">Crush reply options</td>
    <td align="center">Colleague reply options</td>
  </tr>
</table>

## How it works

1. The user copies an incoming message.
2. The client sends `incoming_text`, `role`, `thread_id`, and `user_id` to `POST /v1/replies:generate`.
3. The API loads the thread summary, retrieves similar reply examples, calls the model, and returns exactly three options.
4. When the user copies one option, the client calls `POST /v1/replies:select`.
5. The API stores the accepted reply example and updates the thread summary.

## Retrieval model

This project has two memory paths:

- `thread summary`
  Used for short-term continuity within a specific conversation thread.
- `reply examples`
  Used for semantic retrieval of similar examples through `pgvector`.

This is not document QA RAG. The retrieval layer is optimized for recalling reply examples.

### Retrieval query rewriting

Before vector retrieval, the API rewrites the latest incoming message into a structured retrieval representation.

- By default, this uses a low-temperature LLM rewrite pass
- If the rewrite step fails, the system falls back to a deterministic local rewrite
- The feature is controlled by `ENABLE_LLM_QUERY_REWRITE`

The internal structured rewrite contains fields like:

```json
{
  "normalized_message": "move coffee to friday after work",
  "intent": "reschedule meetup",
  "scenario": "dating meetup scheduling",
  "tone": "playful",
  "entities": ["coffee", "friday", "after work"],
  "retrieval_query": "reschedule coffee meetup friday after work"
}
```

Important: the embedding query is not just the `retrieval_query` field.

The system formats the final retrieval text as a multi-line block and embeds the whole block:

```text
RAW_MESSAGE: Can we move our coffee to Friday after work?
THREAD_CONTEXT: Playful dating chat. Planning first coffee meetup this week.
INTENT: reschedule meetup
SCENARIO: dating meetup scheduling
TONE: playful
ENTITIES: coffee, friday, after work
RETRIEVAL_QUERY: reschedule coffee meetup friday after work
```

This keeps the raw message, thread context, and normalized intent together in the same embedding input.

## Tech stack

- Frontend: Flutter desktop
- Backend: FastAPI, SQLAlchemy, LangChain
- Model provider: Qwen via DashScope OpenAI-compatible API
- Database: PostgreSQL + `pgvector`
- Demo client: vanilla HTML/JS

## Repository layout

```text
api/                      FastAPI app, retrieval flow, prompts, persistence
flutter/                  Primary Flutter desktop client
web/                      Minimal demo web client
data/                     Curated reference dataset
docker/                   PostgreSQL init scripts
tests/                    Python test suite
docker-compose.yml        Local PostgreSQL + pgvector setup
start_api.bat             Start the API on port 8080
start_db.bat              Start local PostgreSQL on port 5432
sync_curated.bat          Force curated dataset sync
AGENTS.md                 Maintainer handoff and architecture notes
```

## Prerequisites

- Python 3.10+
- Flutter 3.24+ with Windows desktop support enabled
- Docker Desktop or another Docker runtime
- A valid Qwen API key

## Environment variables

Create a local `.env` file in the repo root or in `api/`.

```dotenv
QWEN_API_KEY=your_key_here
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_EMBEDDING_DIMENSION=1536

DATABASE_URL=postgresql+psycopg://replycopilot:replycopilot@localhost:5432/replycopilot

RAG_TOP_K=4
THREAD_SUMMARY_MAX_CHARS=800
ENABLE_LLM_QUERY_REWRITE=1

INPUT_RATE_PER_1K=0
OUTPUT_RATE_PER_1K=0
```

Notes:

- `.env` is local-only and should not be committed
- The default local database matches the included Docker Compose setup
- The API expects PostgreSQL, not SQLite
- `ENABLE_LLM_QUERY_REWRITE=1` enables the structured LLM rewrite step before retrieval

## Quick start

Run all commands from the repository root.

### 1. Start PostgreSQL + pgvector

Windows helper:

```powershell
.\start_db.bat
```

Manual equivalent:

```powershell
docker compose up -d postgres
docker compose ps postgres
```

Default local connection string:

```text
postgresql+psycopg://replycopilot:replycopilot@localhost:5432/replycopilot
```

### 2. Start the API

Windows helper:

```powershell
.\start_api.bat
```

Manual equivalent:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r api\requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

If you are using Git Bash, run the API with the virtualenv Python directly:

```bash
./.venv/Scripts/python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

Health check:

```powershell
curl http://127.0.0.1:8080/health
```

### 3. Run the Flutter desktop client

From a new terminal:

```powershell
cd flutter
flutter pub get
flutter run -d windows
```

If Windows desktop support is not enabled yet:

```powershell
flutter config --enable-windows-desktop
flutter doctor
```

The Flutter client expects the API at `http://127.0.0.1:8080`.

Typical local workflow:

1. Start PostgreSQL
2. Start the FastAPI server
3. Open a new terminal
4. Run `cd flutter`
5. Run `flutter pub get`
6. Run `flutter run -d windows`

## Optional clients

### Web demo client

Open `web/index.html` in a browser after the API is running.

## Curated data vs personal data

This repository is intended to include code, setup, and reference data only.

Included:

- `data/curated_reply_examples.jsonl`
- database init scripts
- application source code

Not included:

- local `.env` files
- local virtual environments
- local SQLite files such as `replycopilot.db`
- local PostgreSQL data volumes
- user-specific conversation history
- exported database backups or dumps

That means the repo can be shared publicly without bundling personal reply history, while still keeping the reference dataset needed for cold start behavior.

## Data model

Main persistence tables:

- `users`
- `reply_sessions`
- `conversation_threads`
- `reply_examples`
- `dataset_sync_states`

High-level behavior:

- `reply_sessions` stores each generation request and the three generated options
- `conversation_threads` stores exact per-thread summaries
- `reply_examples` stores curated examples and accepted user selections with embeddings

## API

Base URL: `http://127.0.0.1:8080`

### `GET /`

Returns:

```json
{ "ok": true }
```

### `GET /health`

Returns:

```json
{ "ok": true, "provider": "qwen", "model": "qwen-plus" }
```

### `POST /v1/replies:generate`

Request:

```json
{
  "incoming_text": "string",
  "role": "crush",
  "thread_id": "string",
  "user_id": "optional external identifier"
}
```

Response shape:

```json
{
  "options": ["string", "string", "string"],
  "session_id": "string",
  "meta": {
    "provider": "qwen",
    "model": "qwen-plus",
    "latency_ms": 123,
    "tokens_in": 42,
    "tokens_out": 58,
    "estimated_cost_usd": 0.0,
    "retrieval_used": true,
    "retrieved_examples_count": 3,
    "thread_summary_used": true
  }
}
```

### `POST /v1/replies:select`

Request:

```json
{
  "session_id": "string",
  "thread_id": "string",
  "option_index": 0,
  "user_id": "optional external identifier"
}
```

Response:

```json
{ "ok": true }
```

## Development

### Python tests

```powershell
python -m pytest -q
```

### Flutter checks

```powershell
cd flutter
flutter analyze
flutter test
```

## Troubleshooting

- If the API fails at startup, confirm `DATABASE_URL` points to PostgreSQL and that `pgvector` is available
- If Flutter cannot connect, verify the API is running on `http://127.0.0.1:8080`
- If `flutter run -d windows` fails, run `flutter config --enable-windows-desktop` and then `flutter doctor`
- If Generate returns no clipboard text, copy the source message again before pressing Generate

## Security and privacy

- Phone numbers and email addresses are redacted before LLM generation
- `.env` is intentionally excluded from version control
- Development CORS is open by default and should be restricted before production deployment

## Notes for contributors

- Start the API from the repository root with `python -m uvicorn api.main:app ...`
- If you change the API contract, update the Flutter client and web demo together
- `AGENTS.md` is the quickest architecture handoff for the current implementation
