@echo off
REM Arranca paper-search accesible desde el movil de la misma wifi.
REM
REM Deliberadamente separado de run.bat y con una confirmacion: abrir el
REM servidor a toda la red no debe pasar por hacer doble clic donde no era.

cd /d "%~dp0"

echo.
echo  ================================================================
echo   Vas a abrir paper-search a TODA la red wifi.
echo  ================================================================
echo.
echo   Cualquiera conectado a esta red podra entrar. NO hay contrasena:
echo     - podra leer tus favoritos y tus notas personales,
echo     - podra ver todo lo que has buscado,
echo     - podra lanzar busquedas que gastan tu clave de la API y tu
echo       cuota diaria, y eso cuesta dinero.
echo.
echo   Usalo solo en una red de confianza (tu casa), no en una wifi
echo   publica ni compartida.
echo.

set /p RESPUESTA="  Continuar? [s/N]: "
if /i not "%RESPUESTA%"=="s" (
    echo.
    echo  Cancelado. Para el modo normal, usa run.bat.
    pause
    exit /b 0
)

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

REM Sin `start`: la URL que hace falta es la de la red, y la imprime app.py.
python app.py --red

pause
