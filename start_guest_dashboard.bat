@echo off
rem Guest-only dashboard (view only, guest links only, no password login) on port 8502. Errors show no file paths to guests. Restarts after any exit. ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set QUANT_GUEST_ONLY=1
cd /d "%~dp0"
if not exist C:\quant_data mkdir C:\quant_data
:loop
echo ==== guest dashboard start %date% %time% ==== >> C:\quant_data\guest_dashboard.log
"C:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" -m streamlit run dashboard.py --server.port 8502 --server.headless true --client.showErrorDetails false --theme.base dark --theme.primaryColor "#E5484D" --theme.backgroundColor "#101318" --theme.secondaryBackgroundColor "#191D24" --theme.textColor "#E6E8EB" >> C:\quant_data\guest_dashboard.log 2>&1
timeout /t 30 /nobreak >nul
goto loop
