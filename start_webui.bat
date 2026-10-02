@echo off
title VSE Toolbox WebUI 控制台

echo ========================================================
echo           正在启动 VSE Toolbox WebUI 控制台...
echo ========================================================
echo 工作目录: E:\project\vse-toolbox
echo 访问地址: http://127.0.0.1:5000/
echo 服务就绪后将自动打开默认浏览器。
echo 关闭此窗口即可停止 WebUI 服务。
echo --------------------------------------------------------

cd /d "E:\project\vse-toolbox"

if exist "C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
    set "PYTHON_EXE=C:\Users\Lynch\AppData\Local\Python\pythoncore-3.14-64\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" webui.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo 服务异常退出 (错误代码: %ERRORLEVEL%)
    pause
)
