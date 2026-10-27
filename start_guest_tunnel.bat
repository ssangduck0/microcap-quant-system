@echo off
rem Tunnel for the guest-only dashboard (port 8502). Sends the guest address to Telegram. ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set DASH_PORT=8502
set TUNNEL_KIND=guest
cd /d "%~dp0"
if not exist C:\quant_data mkdir C:\quant_data
:loop
echo ==== guest tunnel start %date% %time% ==== >> C:\quant_data\guest_tunnel.log
"C:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" tunnel.py >> C:\quant_data\guest_tunnel.log 2>&1
timeout /t 60 /nobreak >nul
goto loop
