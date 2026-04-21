@echo off
REM Windows exe build. Run from PowerShell or cmd:
REM     build.bat
REM Output: dist\Petris.exe
setlocal

cd /d "%~dp0"

echo [1/3] installing build deps...
py -m pip install --upgrade pip pyinstaller >nul
py -m pip install -r requirements.txt

echo [2/3] cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] building...
py -m PyInstaller --clean --noconfirm Petris.spec

echo.
if exist dist\Petris.exe (
    echo done. binary: dist\Petris.exe
    for %%A in (dist\Petris.exe) do echo size: %%~zA bytes
) else (
    echo build failed.
    exit /b 1
)
