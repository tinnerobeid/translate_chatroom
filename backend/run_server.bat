@echo off
cd /d "c:\Users\Hp\Documents\translate_chat\backend"
echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt

echo.
echo Starting FastAPI backend server on http://localhost:8000
echo Press Ctrl+C to stop the server
echo.

uvicorn main:app --reload --host localhost --port 8000
