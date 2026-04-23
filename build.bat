@echo off
REM Windows exe build. Run from PowerShell or cmd:
REM     build.bat
REM Output: dist\Petris.exe
setlocal

REM pushd (unlike "cd /d") maps a temporary drive letter for UNC paths,
REM so this works when run from a \\wsl.localhost\... path.
pushd "%~dp0" || (echo failed to cd to script dir & exit /b 1)

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
    popd
) else (
    echo build failed.
    popd
    exit /b 1
)
