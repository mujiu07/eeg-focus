@echo off
rem Double-click to start Focus Frog on Windows.
rem Thin wrapper so users don't need to touch PowerShell execution policy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 pause
