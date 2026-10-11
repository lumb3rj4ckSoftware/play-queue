@echo off
rem Kompatibilitaetsstarter: keine Ollama-Installation mehr erforderlich.
cd /d "%~dp0"
set "PLAYQUEUE_AI_ENABLED=1"
call start.bat
