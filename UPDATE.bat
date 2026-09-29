@echo off
REM ============================================================
REM  UPDATE.bat
REM  Double-click this any time after changing .py files.
REM  Rebuilds SourceMaterialFetcher.exe from the code currently in
REM  this folder and puts the finished exe in ONE place:
REM
REM      release\SourceMaterialFetcher.exe
REM
REM  That release\ folder is the only thing you ever need to grab
REM  for a manual GitHub Release upload. It is git-ignored, so it
REM  can never be committed to the repo by accident. The temporary
REM  build\ and dist\ folders are deleted when the build finishes.
REM ============================================================

cd /d "%~dp0"

if not exist ".venv" (
    echo First-time setup: creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing/checking dependencies...
pip install --upgrade pip >nul
pip install -r requirements.txt >nul
pip install pyinstaller >nul

echo.
echo Cleaning previous build...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
rmdir /s /q release 2>nul

echo Building SourceMaterialFetcher.exe from current source...
pyinstaller --noconfirm SourceMaterialFetcher.spec

if not exist "dist\SourceMaterialFetcher.exe" (
    echo.
    echo BUILD FAILED - scroll up to see the error above.
    pause
    exit /b 1
)

mkdir release
move /y "dist\SourceMaterialFetcher.exe" "release\SourceMaterialFetcher.exe" >nul

echo Cleaning up temporary build folders...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo.
echo ============================================================
echo   Done. Your exe is at: release\SourceMaterialFetcher.exe
echo ============================================================
start "" "release"
pause
