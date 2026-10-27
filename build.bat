@echo off
rem Builds FishingMacro.exe from fishing_macro.py (requires Python 3.9+).
rem Double-click it, or run "build.bat nopause" from a terminal.
setlocal
cd /d "%~dp0"

tasklist /fi "imagename eq FishingMacro.exe" 2>nul | find /i "FishingMacro.exe" >nul
if not errorlevel 1 (
    echo FishingMacro.exe is running. Close it first, then build again.
    goto :error
)
if exist ".venv\Scripts\python.exe" goto :have_venv
call :find_python
if not defined PY (
    echo Python 3 was not found. Install it from https://www.python.org/ and try again.
    goto :error
)
%PY% -m venv .venv || goto :error
:have_venv
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pyinstaller || goto :error
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
    --icon fishing.ico --add-data "fishing.ico;." --name FishingMacro fishing_macro.py || goto :error
copy /y "dist\FishingMacro.exe" "FishingMacro.exe" >nul || goto :error

echo.
echo Done: %~dp0FishingMacro.exe
if /i not "%~1"=="nopause" pause
exit /b 0

:error
echo.
echo Build failed.
if /i not "%~1"=="nopause" pause
exit /b 1

rem Sets PY to a real Python 3 (the "python" on PATH may be the Microsoft Store stub).
:find_python
py -3 -c "import sys" >nul 2>&1 && (set "PY=py -3" & exit /b 0)
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do (
    if exist "%%~D\python.exe" set PY="%%~D\python.exe"
)
if defined PY exit /b 0
python -c "import sys" >nul 2>&1 && (set "PY=python" & exit /b 0)
exit /b 1
