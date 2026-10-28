@echo off
rem wrap — direct-invoke shim when npm's generated .cmd isn't on PATH.
rem Defers to wrap.js (node): bash on POSIX, python wrap_cli.py here.
setlocal
set "ROOT=%~dp0.."
where node >nul 2>nul
if not errorlevel 1 goto :node
rem no node — run the python port directly. `python --version` filters
rem out the Microsoft Store alias stub (it exists on PATH but fails).
set PY=
python --version >nul 2>nul && set PY=python
if not defined PY ( python3 --version >nul 2>nul && set PY=python3 )
if not defined PY ( py -3 --version >nul 2>nul && set PY=py -3 )
if not defined PY (
  echo wrap: node or python required >&2
  exit /b 1
)
%PY% "%ROOT%\server\wrap_cli.py" %*
exit /b %errorlevel%

:node
node "%ROOT%\bin\wrap.js" %*
exit /b %errorlevel%
