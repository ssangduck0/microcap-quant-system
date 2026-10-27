@echo off
rem Allow the dashboard (port 8501) to be opened from your phone (Tailscale or home Wi-Fi).
rem Right-click this file and choose "Run as administrator". ASCII only.
netsh advfirewall firewall delete rule name="Quant Dashboard 8501" >nul 2>&1
netsh advfirewall firewall add rule name="Quant Dashboard 8501" dir=in action=allow protocol=TCP localport=8501 profile=any
if errorlevel 1 (
  echo FAILED. Right-click this file and choose "Run as administrator".
) else (
  echo OK. On your phone open  http://[this PC Tailscale IP]:8501
)
pause
