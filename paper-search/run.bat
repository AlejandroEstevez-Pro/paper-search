@echo off
REM Doble clic aqui para arrancar paper-search con interfaz web.
REM Activa el venv si existe, instala dependencias si faltan, arranca el
REM servidor local y abre el navegador solo.

cd /d "%~dp0"

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo [aviso] No se encontro venv\. Ejecutando con el Python del sistema.
)

pip show flask >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias por primera vez, un momento...
    pip install -r requirements.txt
)

start "" http://127.0.0.1:5000
python app.py

pause
