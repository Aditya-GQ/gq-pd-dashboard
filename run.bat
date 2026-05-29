@echo off
echo Starting GQ Intelligence Dashboard (Python 3.11)...
call "%~dp0venv311\Scripts\activate.bat"
streamlit run "%~dp0app.py"
