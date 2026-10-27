@echo off
rem Phone access: Cloudflare quick tunnel to the dashboard. Restarts after any exit. Needs DASH_PASSWORD in .env and cloudflared. ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist C:\quant_data mkdir C:\quant_data
:loop
echo ==== tunnel start %date% %time% ==== >> C:\quant_data\tunnel.log
"C:\Users\admin\AppData\Local\Programs\Python\Python314\python.exe" tunnel.py >> C:\quant_data\tunnel.log 2>&1
timeout /t 60 /nobreak >nul
goto loop
