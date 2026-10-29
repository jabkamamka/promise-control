# Запуск сервиса контроля обещаний на Windows.
# Использование:  .\run.ps1            (порт 8080)
#                 .\run.ps1 -Port 9000
param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Создаю виртуальное окружение .venv ..." -ForegroundColor Cyan
    python -m venv .venv
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "Устанавливаю зависимости ..." -ForegroundColor Cyan
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -r requirements.txt

Write-Host ""
Write-Host "Сервис запускается: http://localhost:$Port/" -ForegroundColor Green
Write-Host "Документация API:   http://localhost:$Port/docs" -ForegroundColor Green
Write-Host "Вебхук:             http://localhost:$Port/webhook/calls" -ForegroundColor Green
Write-Host ""

& $python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
