@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 python -m venv .venv
 if errorlevel 1 goto failed
)
call .venv\Scripts\activate.bat
python -m pip install "torch>=2.5,<3" --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo PlayQueue startet mit direkt eingebautem lokalen KI-Modell.
echo Beim ersten Start werden die Modelldateien im Hintergrund geladen.
echo Admin: http://127.0.0.1:5050/admin
python app.py
pause
exit /b
:failed
echo Installation fehlgeschlagen. Bitte die Fehlermeldung oben pruefen.
pause
exit /b 1
