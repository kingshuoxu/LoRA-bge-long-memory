@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%app"
set "PYTHONUNBUFFERED=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "LORA_MEMORY_UI=%ROOT%ui"
if exist "%ROOT%runtime\python.exe" (
  "%ROOT%runtime\python.exe" -m memory_core.e2e_check %*
) else (
  "%ROOT%runtime\bin\python3" -m memory_core.e2e_check %*
)
