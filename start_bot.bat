@echo off
echo Activando entorno virtual...
call venv\Scripts\activate.bat
echo Iniciando bot...
python monitor_criptos.py

pause
