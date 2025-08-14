#!/usr/bin/env python3
"""
Windows Development Build Script
专用于开发环境的Windows构建脚本
"""

import os
import sys
import argparse
from pathlib import Path

# 导入主构建脚本的必要函数
from build import (
    get_version, 
    build_flutter_windows, 
    get_features, 
    make_parser,
    check_build_environment,
    system2
)

def main():
    # 强制检查是否在Windows环境
    if not os.name == 'nt':
        print("错误：此脚本只能在Windows环境下运行")
        sys.exit(-1)
    
    print("=== Windows 开发环境构建脚本 ===")
    
    # 检查构建环境
    if not check_build_environment():
        sys.exit(-1)
    
    parser = make_parser()
    args = parser.parse_args()
    
    # 强制设置为Flutter构建（推荐）
    if not args.flutter:
        print("提示：建议使用 --flutter 参数进行Flutter构建")
        response = input("是否继续Flutter构建？(Y/n): ")
        if response.lower() not in ['', 'y', 'yes']:
            print("退出构建")
            sys.exit(0)
        args.flutter = True
    
    version = get_version()
    features = ','.join(get_features(args))
    
    print(f"版本: {version}")
    print(f"功能特性: {features}")
    print(f"Flutter构建: {args.flutter}")
    
    # 构建虚拟显示库
    print("构建虚拟显示库...")
    os.chdir('libs/virtual_display/dylib')
    system2('cargo build --release')
    os.chdir('../../..')
    
    if args.flutter:
        print("开始Flutter Windows构建...")
        build_flutter_windows(version, features, getattr(args, 'skip_portable_pack', False))
        print(" Windows Flutter构建完成！")
    else:
        print("开始原生Windows构建...")
        system2('cargo build --release --features ' + features)
        system2('mv target/release/rustdesk.exe target/release/RustDesk.exe')
        print(" Windows原生构建完成！")
    
    print(f"构建输出位置: {os.path.abspath('.')}")

if __name__ == "__main__":
    main()