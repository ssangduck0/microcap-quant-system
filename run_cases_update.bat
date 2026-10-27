@echo off
rem Daily update of the past-cases DB (for Windows Task Scheduler). Keep this file ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo ==== %date% %time% ==== >> C:\quant_data\cases_update.log
"C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe" cases.py update >> C:\quant_data\cases_update.log 2>&1
