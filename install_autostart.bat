@echo off
rem Registers the scanner, dashboard and phone tunnel to start at logon through the Startup folder (no admin rights needed). ASCII only.
set "QUANT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$dir=$env:QUANT_DIR; $w=New-Object -ComObject WScript.Shell; $su=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'; foreach($n in 'start_scanner','start_dashboard','start_tunnel','start_guest_dashboard','start_guest_tunnel','start_collector'){ $bat=Join-Path $dir ($n+'.bat'); if(-not (Test-Path $bat)){ Write-Host ('NOT FOUND: '+$bat); continue }; $s=$w.CreateShortcut((Join-Path $su ('Quant_'+$n+'.lnk'))); $s.TargetPath=$bat; $s.WorkingDirectory=$dir; $s.WindowStyle=7; $s.Save(); Write-Host ('OK: '+$s.FullName) }"
echo.
echo Done. Sign out and in again to start them (or double-click the shortcuts in the Startup folder).
echo To remove: run uninstall_autostart.bat
pause
