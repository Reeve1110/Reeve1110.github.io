@echo off
setlocal
rem 启动摄影站管理工具（无控制台黑窗）
set "PY=D:\tool\Python\Python314\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
start "" "%PY%" "%~dp0scripts\admin_gui.py"
