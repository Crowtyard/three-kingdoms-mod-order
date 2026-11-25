@echo off
chcp 65001 >nul
set PYTHONUTF8=1
python "%~dp0sort_mods.py" restore
echo.
pause
