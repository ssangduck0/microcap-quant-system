@echo off
rem Auto-start the scanner (for Windows Task Scheduler "at logon"). Restarts it 30 seconds after any exit. ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist C:\quant_data mkdir C:\quant_data
:loop
echo ==== scanner start %date% %time% ==== >> C:\quant_data\scanner.log
"C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe" scanner.py >> C:\quant_data\scanner.log 2>&1
timeout /t 30 /nobreak >nul
goto loop
