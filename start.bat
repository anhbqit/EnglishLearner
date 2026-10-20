@echo off
cd /d "%~dp0"
set PY=python
for /d %%D in ("%LOCALAPPDATA%\hermes\tools\python-3.14.7*") do set PY=%%D\python.exe
:again
"%PY%" server.py
if %errorlevel%==3 goto again
