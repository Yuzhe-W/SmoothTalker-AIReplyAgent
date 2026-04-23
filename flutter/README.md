# Flutter Desktop Client

This folder contains the primary Windows desktop client for SmoothTalker. It talks to the FastAPI API in the repo root and expects the backend on `http://127.0.0.1:8080`.

## Prerequisites

- Flutter 3.24+ with Windows desktop support enabled
- Python 3.10+
- PostgreSQL with `pgvector`
- A configured `.env` in the repo root or `api/` with Qwen and database settings

## Start the API

Run from the repository root:

```powershell
docker compose up -d postgres
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r api\requirements.txt
python -m uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

If you are using Git Bash, start the API like this instead:

```bash
./.venv/Scripts/python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
```

`start_db.bat` starts the local PostgreSQL + `pgvector` container, and `start_api.bat` starts the API on Windows.

## Run the Flutter App

From a new terminal after the API is running:

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

## Behavior Notes

- Copy source text before clicking **Generate**.
- Each role keeps its own `thread_id`; do not leave it blank if you want conversation consistency.
- Copying one of the generated replies calls `/v1/replies:select`, which stores the accepted example and updates thread memory.
- The Flutter client is the primary desktop experience for this project.

For API details, environment variables, and the full architecture, see the root [README](../README.md).
