@echo off
rem Auto-start the dashboard (for Windows Task Scheduler "at logon"). Restarts it 30 seconds after any exit. ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist C:\quant_data mkdir C:\quant_data
:loop
echo ==== dashboard start %date% %time% ==== >> C:\quant_data\dashboard.log
"C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe" -m streamlit run dashboard.py --server.headless true --theme.base dark --theme.primaryColor "#E5484D" --theme.backgroundColor "#101318" --theme.secondaryBackgroundColor "#191D24" --theme.textColor "#E6E8EB" >> C:\quant_data\dashboard.log 2>&1
timeout /t 30 /nobreak >nul
goto loop
