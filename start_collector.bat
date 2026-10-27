@echo off
rem All-day collector: SEC 8-K/6-K press releases (3 years) and price reactions. Resumes where it stopped. ASCII only.
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist C:\quant_data mkdir C:\quant_data
:loop
echo ==== collector start %date% %time% ==== >> C:\quant_data\collector.log
"C:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" eventlab.py run >> C:\quant_data\collector.log 2>&1
timeout /t 120 /nobreak >nul
goto loop
