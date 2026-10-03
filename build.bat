@echo off
cd /d "%~dp0"
echo ============================================
echo   MP4 Cutter - Windows build
echo ============================================
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install from https://www.python.org/downloads/
  echo         and CHECK "Add python.exe to PATH" during install.
  pause
  exit /b 1
)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :fail
pyinstaller --noconfirm --windowed --name MP4Cutter --collect-all imageio_ffmpeg mp4_cutter.py || goto :fail
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
  %ISCC% installer.iss || goto :fail
  echo.
  echo DONE! Installer: installer_output\MP4Cutter_Setup.exe
  explorer installer_output
) else (
  echo.
  echo DONE! Program folder: dist\MP4Cutter  (run MP4Cutter.exe)
  echo To make an installer, install Inno Setup 6 from https://jrsoftware.org/isdl.php and run this again.
  explorer dist\MP4Cutter
)
pause
exit /b 0
:fail
echo [ERROR] Build failed. See messages above.
pause
exit /b 1
