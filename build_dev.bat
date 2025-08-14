@echo off
REM Windows 开发环境快速构建脚本
echo === LinsDesk Windows 开发构建 ===

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误：未找到Python，请先安装Python
    pause
    exit /b 1
)

REM 检查Rust
cargo --version >nul 2>&1
if errorlevel 1 (
    echo 错误：未找到Cargo，请先安装Rust
    pause
    exit /b 1
)

REM 检查Flutter
flutter --version >nul 2>&1
if errorlevel 1 (
    echo 错误：未找到Flutter，请先安装Flutter
    pause
    exit /b 1
)

echo 开始构建...
python build.py --flutter %*

if errorlevel 1 (
    echo 构建失败！
    pause
    exit /b 1
)

echo 构建成功！
pause