@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe python -m venv .venv
if errorlevel 1 goto failed
call .venv\Scripts\activate.bat
python -m pip install "torch>=2.5,<3" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
python alias_ai.py
if errorlevel 1 goto failed
pause
exit /b
:failed
echo Modellvorbereitung fehlgeschlagen. Details stehen oben.
pause
exit /b 1
