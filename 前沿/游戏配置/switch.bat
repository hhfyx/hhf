@echo off
setlocal

REM Game config switcher
REM Usage: switch.bat baseline ^| delta ^| cs2  (or 1 ^| 2 ^| 3)

if "%~1"=="" goto usage

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0switch.ps1" -Profile "%~1" %2
set RC=%ERRORLEVEL%
if not "%RC%"=="0" pause
exit /b %RC%

:usage
echo Usage: switch.bat ^<profile^>
echo.
echo   1 or baseline  = restore original
echo   2 or delta     = Delta Force smooth
echo   3 or cs2       = CS2 smooth
echo.
echo Example:  switch.bat cs2
exit /b 1
