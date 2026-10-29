@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv" (
    echo Создаю виртуальное окружение...
    python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo.
echo Сервис контроля обещаний: http://127.0.0.1:8000/dashboard
echo Документация API:              http://127.0.0.1:8000/docs
echo Остановить: Ctrl+C
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
