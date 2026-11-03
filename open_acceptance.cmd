@echo off
setlocal
set "ACCEPTANCE_PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if not exist "%ACCEPTANCE_PWSH%" (
  where pwsh.exe >nul 2>nul
  if errorlevel 1 (
    echo PowerShell 7 is required. See board/acceptance_computer_operations.md.
    pause
    exit /b 1
  )
  set "ACCEPTANCE_PWSH=pwsh.exe"
)
"%ACCEPTANCE_PWSH%" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0board\open_acceptance.ps1" %*
if errorlevel 1 pause
endlocal
