@echo off
rem Double-clic : ouvre DS Decomp Studio dans sa fenetre (desktop\, programme Rust + WebView2).
rem Studio.cmd web : ancien mode, serveur dans cette console + navigateur (http://127.0.0.1:8765).
cd /d "%~dp0"
set EXE=%~dp0desktop\target\release\DSDecompStudio.exe
if /i not "%~1"=="web" if exist "%EXE%" (
  start "" "%EXE%"
  exit /b 0
)
if /i "%~1"=="web" shift
if not exist "%EXE%" if /i not "%~1"=="serve" echo (fenetre du studio pas encore compilee : desktop\build.cmd ; ouverture dans le navigateur)
set PY=%~dp0..\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python
"%PY%" studio.py %1 %2 %3 %4 %5 %6 %7 %8 %9
pause
