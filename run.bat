@echo off
REM Arranca Quiz Video Studio en http://localhost:8000
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000
