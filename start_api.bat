@echo off
setlocal
echo Starting SmoothTalker API Server...
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing dependencies...
python -m pip install -r api\requirements.txt
echo Starting server on http://localhost:8080
python -m uvicorn api.main:app --host 0.0.0.0 --port 8080 --reload
pause
