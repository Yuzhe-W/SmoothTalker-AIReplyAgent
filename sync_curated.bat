@echo off
setlocal
if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
echo Installing dependencies...
python -m pip install -r api\requirements.txt
echo Syncing curated reply examples...
python -m api.sync_curated --force
pause
