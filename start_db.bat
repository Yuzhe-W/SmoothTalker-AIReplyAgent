@echo off
echo Starting local PostgreSQL + pgvector for SmoothTalker...
docker compose up -d postgres
if errorlevel 1 (
  echo Failed to start Docker Compose service.
  pause
  exit /b 1
)
docker compose ps postgres
echo Local database is expected at postgresql+psycopg://replycopilot:replycopilot@localhost:5432/replycopilot
pause
