@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo.
echo  ---------------------------------------------------
echo   GolfAdmin  -  http://127.0.0.1:5000
echo   admin / admin  *  manager / manager  *  cashier / cashier
echo  ---------------------------------------------------
echo.
python run.py
pause
