@echo off
rem Removes the startup shortcuts created by install_autostart.bat. ASCII only.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quant_start_scanner.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quant_start_dashboard.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quant_start_tunnel.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quant_start_guest_dashboard.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quant_start_guest_tunnel.lnk" 2>nul
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Quant_start_collector.lnk" 2>nul
echo Removed.
pause
