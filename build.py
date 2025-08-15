#!/usr/bin/env python3

import os
import pathlib
import platform
import zipfile
import urllib.request
import shutil
import hashlib
import argparse
import sys
from pathlib import Path

windows = platform.platform().startswith('Windows')
osx = platform.platform().startswith(
    'Darwin') or platform.platform().startswith("macOS")
hbb_name = 'rustdesk' + ('.exe' if windows else '')
exe_path = 'target/release/' + hbb_name
if windows:
    flutter_build_dir = 'build/windows/x64/runner/Release/'
elif osx:
    flutter_build_dir = 'build/macos/Build/Products/Release/'
else:
    flutter_build_dir = 'build/linux/x64/release/bundle/'
flutter_build_dir_2 = f'flutter/{flutter_build_dir}'
skip_cargo = False


def get_deb_arch() -> str:
    custom_arch = os.environ.get("DEB_ARCH")
    if custom_arch is None:
        return "amd64"
    return custom_arch

def get_deb_extra_depends() -> str:
    custom_arch = os.environ.get("DEB_ARCH")
    if custom_arch == "armhf": # for arm32v7 libsciter-gtk.so
        return ", libatomic1"
    return ""

def system2(cmd, check_result=True, show_output=True):
    """执行系统命令，带有更好的错误处理"""
    if show_output:
        print(f"Executing: {cmd}")
    
    exit_code = os.system(cmd)
    
    if check_result and exit_code != 0:
        error_msg = f"Command failed with exit code {exit_code}: {cmd}"
        sys.stderr.write(f"Error: {error_msg}\n")
        
        # 提供可能的解决建议
        if 'cargo build' in cmd:
            sys.stderr.write("Possible solutions for cargo build failure:\n")
            sys.stderr.write("1. Run 'cargo clean' to clean previous builds\n")
            sys.stderr.write("2. Check Rust toolchain version compatibility\n")
            sys.stderr.write("3. Ensure all dependencies are properly installed\n")
            sys.stderr.write("4. Check for compilation errors in the code\n")
            sys.stderr.write("5. Check Cargo.toml for dependency conflicts\n")
        elif 'flutter build' in cmd:
            sys.stderr.write("Possible solutions for flutter build failure:\n")
            sys.stderr.write("1. Run 'flutter clean' to clean previous builds\n")
            sys.stderr.write("2. Run 'flutter pub get' to update dependencies\n")
            sys.stderr.write("3. Check Flutter SDK version compatibility\n")
            sys.stderr.write("4. Ensure target platform is correctly specified (x64)\n")
        
        sys.exit(-1)
    
    return exit_code


def get_version():
    with open("Cargo.toml", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("version"):
                return line.replace("version", "").replace("=", "").replace('"', '').strip()
    return ''


def parse_rc_features(feature):
    available_features = {}
    apply_features = {}
    if not feature:
        feature = []

    def platform_check(platforms):
        if windows:
            return 'windows' in platforms
        elif osx:
            return 'osx' in platforms
        else:
            return 'linux' in platforms

    def get_all_features():
        features = []
        for (feat, feat_info) in available_features.items():
            if platform_check(feat_info['platform']):
                features.append(feat)
        return features

    if isinstance(feature, str) and feature.upper() == 'ALL':
        return get_all_features()
    elif isinstance(feature, list):
        if windows:
            # download third party is deprecated, we use github ci instead.
            # feature.append('PrivacyMode')
            pass
        for feat in feature:
            if isinstance(feat, str) and feat.upper() == 'ALL':
                return get_all_features()
            if feat in available_features:
                if platform_check(available_features[feat]['platform']):
                    apply_features[feat] = available_features[feat]
            else:
                print(f'Unrecognized feature {feat}')
        return apply_features
    else:
        raise Exception(f'Unsupported features param {feature}')


def make_parser():
    parser = argparse.ArgumentParser(description='Build script.')
    parser.add_argument(
        '-f',
        '--feature',
        dest='feature',
        metavar='N',
        type=str,
        nargs='+',
        default='',
        help='Integrate features, windows only.'
             'Available: [Not used for now]. Special value is "ALL" and empty "". Default is empty.')
    parser.add_argument('--flutter', action='store_true',
                        help='Build flutter package', default=False)
    parser.add_argument(
        '--hwcodec',
        action='store_true',
        help='Enable feature hwcodec' + (
            '' if windows or osx else ', need libva-dev.')
    )
    parser.add_argument(
        '--vram',
        action='store_true',
        help='Enable feature vram, only available on windows now.'
    )
    parser.add_argument(
        '--portable',
        action='store_true',
        help='Build windows portable'
    )
    parser.add_argument(
        '--unix-file-copy-paste',
        action='store_true',
        help='Build with unix file copy paste feature'
    )
    parser.add_argument(
        '--skip-cargo',
        action='store_true',
        help='Skip cargo build process, only flutter version + Linux supported currently'
    )
    if windows:
        parser.add_argument(
            '--skip-portable-pack',
            action='store_true',
            help='Skip packing, only flutter version + Windows supported'
        )
    parser.add_argument(
        "--package",
        type=str
    )
    if osx:
        parser.add_argument(
            '--screencapturekit',
            action='store_true',
            help='Enable feature screencapturekit'
        )
    return parser


# Generate build script for docker
#
# it assumes all build dependencies are installed in environments
# Note: do not use it in bare metal, or may break build environments
def generate_build_script_for_docker():
    with open("/tmp/build.sh", "w") as f:
        f.write('''
            #!/bin/bash
            # environment
            export CPATH="$(clang -v 2>&1 | grep "Selected GCC installation: " | cut -d' ' -f4-)/include"
            # flutter
            pushd /opt
            wget https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.0.5-stable.tar.xz
            tar -xvf flutter_linux_3.0.5-stable.tar.xz
            export PATH=`pwd`/flutter/bin:$PATH
            popd
            # flutter_rust_bridge
            dart pub global activate ffigen --version 5.0.1
            pushd /tmp && git clone https://github.com/SoLongAndThanksForAllThePizza/flutter_rust_bridge --depth=1 && popd
            pushd /tmp/flutter_rust_bridge/frb_codegen && cargo install --path . && popd
            pushd flutter && flutter pub get && popd
            ~/.cargo/bin/flutter_rust_bridge_codegen --rust-input ./src/flutter_ffi.rs --dart-output ./flutter/lib/generated_bridge.dart
            # install vcpkg
            pushd /opt
            export VCPKG_ROOT=`pwd`/vcpkg
            git clone https://github.com/microsoft/vcpkg
            vcpkg/bootstrap-vcpkg.sh
            popd
            $VCPKG_ROOT/vcpkg install --x-install-root="$VCPKG_ROOT/installed"
            # build rustdesk
            ./build.py --flutter --hwcodec
        ''')
    system2("chmod +x /tmp/build.sh")
    system2("bash /tmp/build.sh")


# Downloading third party resources is deprecated.
# We can use this function in an offline build environment.
# Even in an online environment, we recommend building third-party resources yourself.
def download_extract_features(features, res_dir):
    import re

    proxy = ''

    def req(url):
        if not proxy:
            return url
        else:
            r = urllib.request.Request(url)
            r.set_proxy(proxy, 'http')
            r.set_proxy(proxy, 'https')
            return r

    for (feat, feat_info) in features.items():
        includes = feat_info['include'] if 'include' in feat_info and feat_info['include'] else []
        includes = [re.compile(p) for p in includes]
        excludes = feat_info['exclude'] if 'exclude' in feat_info and feat_info['exclude'] else []
        excludes = [re.compile(p) for p in excludes]

        print(f'{feat} download begin')
        download_filename = feat_info['zip_url'].split('/')[-1]
        checksum_md5_response = urllib.request.urlopen(
            req(feat_info['checksum_url']))
        for line in checksum_md5_response.read().decode('utf-8').splitlines():
            if line.split()[1] == download_filename:
                checksum_md5 = line.split()[0]
                filename, _headers = urllib.request.urlretrieve(feat_info['zip_url'],
                                                                download_filename)
                md5 = hashlib.md5(open(filename, 'rb').read()).hexdigest()
                if checksum_md5 != md5:
                    raise Exception(f'{feat} download failed')
                print(f'{feat} download end. extract bein')
                zip_file = zipfile.ZipFile(filename)
                zip_list = zip_file.namelist()
                for f in zip_list:
                    file_exclude = False
                    for p in excludes:
                        if p.match(f) is not None:
                            file_exclude = True
                            break
                    if file_exclude:
                        continue

                    file_include = False if includes else True
                    for p in includes:
                        if p.match(f) is not None:
                            file_include = True
                            break
                    if file_include:
                        print(f'extract file {f}')
                        zip_file.extract(f, res_dir)
                zip_file.close()
                os.remove(download_filename)
                print(f'{feat} extract end')


def external_resources(flutter, args, res_dir):
    features = parse_rc_features(args.feature)
    if not features:
        return

    print(f'Build with features {list(features.keys())}')
    if os.path.isdir(res_dir) and not os.path.islink(res_dir):
        shutil.rmtree(res_dir)
    elif os.path.exists(res_dir):
        raise Exception(f'Find file {res_dir}, not a directory')
    os.makedirs(res_dir, exist_ok=True)
    download_extract_features(features, res_dir)
    if flutter:
        os.makedirs(flutter_build_dir_2, exist_ok=True)
        for f in pathlib.Path(res_dir).iterdir():
            print(f'{f}')
            if f.is_file():
                shutil.copy2(f, flutter_build_dir_2)
            else:
                shutil.copytree(f, f'{flutter_build_dir_2}{f.stem}')


def get_features(args):
    features = ['inline'] if not args.flutter else []
    if args.hwcodec:
        features.append('hwcodec')
    if args.vram:
        features.append('vram')
    if args.flutter:
        features.append('flutter')
    # unix-file-copy-paste 仅在 Unix 系统上可用
    if args.unix_file_copy_paste and not windows:
        features.append('unix-file-copy-paste')
    elif args.unix_file_copy_paste and windows:
        print("Warning: unix-file-copy-paste feature is not available on Windows, skipping...")
    if osx:
        if args.screencapturekit:
            features.append('screencapturekit')
    print("features:", features)
    return features


def generate_control_file(version):
    control_file_path = "../res/DEBIAN/control"
    system2('/bin/rm -rf %s' % control_file_path)

    content = """Package: rustdesk
Section: net
Priority: optional
Version: %s
Architecture: %s
Maintainer: rustdesk <info@rustdesk.com>
Homepage: https://rustdesk.com
Depends: libgtk-3-0, libxcb-randr0, libxdo3, libxfixes3, libxcb-shape0, libxcb-xfixes0, libasound2, libsystemd0, curl, libva2, libva-drm2, libva-x11-2, libgstreamer-plugins-base1.0-0, libpam0g, gstreamer1.0-pipewire%s
Recommends: libayatana-appindicator3-1
Description: A remote control software.

""" % (version, get_deb_arch(), get_deb_extra_depends())
    file = open(control_file_path, "w")
    file.write(content)
    file.close()


def ffi_bindgen_function_refactor():
    # workaround ffigen
    system2(
        'sed -i "s/ffi.NativeFunction<ffi.Bool Function(DartPort/ffi.NativeFunction<ffi.Uint8 Function(DartPort/g" flutter/lib/generated_bridge.dart')


def build_flutter_deb(version, features):
    if not skip_cargo:
        system2(f'cargo build --features {features} --lib --release')
        ffi_bindgen_function_refactor()
    os.chdir('flutter')
    system2('flutter build linux --release')
    system2('mkdir -p tmpdeb/usr/bin/')
    system2('mkdir -p tmpdeb/usr/share/rustdesk')
    system2('mkdir -p tmpdeb/etc/rustdesk/')
    system2('mkdir -p tmpdeb/etc/pam.d/')
    system2('mkdir -p tmpdeb/usr/share/rustdesk/files/systemd/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    system2('mkdir -p tmpdeb/usr/share/applications/')
    system2('mkdir -p tmpdeb/usr/share/polkit-1/actions')
    system2('rm tmpdeb/usr/bin/rustdesk || true')
    system2(
        f'cp -r {flutter_build_dir}/* tmpdeb/usr/share/rustdesk/')
    system2(
        'cp ../res/rustdesk.service tmpdeb/usr/share/rustdesk/files/systemd/')
    system2(
        'cp ../res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/rustdesk.png')
    system2(
        'cp ../res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/rustdesk.svg')
    system2(
        'cp ../res/rustdesk.desktop tmpdeb/usr/share/applications/rustdesk.desktop')
    system2(
        'cp ../res/rustdesk-link.desktop tmpdeb/usr/share/applications/rustdesk-link.desktop')
    system2(
        'cp ../res/startwm.sh tmpdeb/etc/rustdesk/')
    system2(
        'cp ../res/xorg.conf tmpdeb/etc/rustdesk/')
    system2(
        'cp ../res/pam.d/rustdesk.debian tmpdeb/etc/pam.d/rustdesk')
    system2(
        "echo \"#!/bin/sh\" >> tmpdeb/usr/share/rustdesk/files/polkit && chmod a+x tmpdeb/usr/share/rustdesk/files/polkit")

    system2('mkdir -p tmpdeb/DEBIAN')
    generate_control_file(version)
    system2('cp -a ../res/DEBIAN/* tmpdeb/DEBIAN/')
    md5_file_folder("tmpdeb/")
    system2('dpkg-deb -b tmpdeb rustdesk.deb;')

    system2('/bin/rm -rf tmpdeb/')
    system2('/bin/rm -rf ../res/DEBIAN/control')
    os.rename('rustdesk.deb', '../rustdesk-%s.deb' % version)
    os.chdir("..")


def build_deb_from_folder(version, binary_folder):
    os.chdir('flutter')
    system2('mkdir -p tmpdeb/usr/bin/')
    system2('mkdir -p tmpdeb/usr/share/rustdesk')
    system2('mkdir -p tmpdeb/usr/share/rustdesk/files/systemd/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    system2('mkdir -p tmpdeb/usr/share/applications/')
    system2('mkdir -p tmpdeb/usr/share/polkit-1/actions')
    system2('rm tmpdeb/usr/bin/rustdesk || true')
    system2(
        f'cp -r ../{binary_folder}/* tmpdeb/usr/share/rustdesk/')
    system2(
        'cp ../res/rustdesk.service tmpdeb/usr/share/rustdesk/files/systemd/')
    system2(
        'cp ../res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/rustdesk.png')
    system2(
        'cp ../res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/rustdesk.svg')
    system2(
        'cp ../res/rustdesk.desktop tmpdeb/usr/share/applications/rustdesk.desktop')
    system2(
        'cp ../res/rustdesk-link.desktop tmpdeb/usr/share/applications/rustdesk-link.desktop')
    system2(
        "echo \"#!/bin/sh\" >> tmpdeb/usr/share/rustdesk/files/polkit && chmod a+x tmpdeb/usr/share/rustdesk/files/polkit")

    system2('mkdir -p tmpdeb/DEBIAN')
    generate_control_file(version)
    system2('cp -a ../res/DEBIAN/* tmpdeb/DEBIAN/')
    md5_file_folder("tmpdeb/")
    system2('dpkg-deb -b tmpdeb rustdesk.deb;')

    system2('/bin/rm -rf tmpdeb/')
    system2('/bin/rm -rf ../res/DEBIAN/control')
    os.rename('rustdesk.deb', '../rustdesk-%s.deb' % version)
    os.chdir("..")


def build_flutter_dmg(version, features):
    if not skip_cargo:
        # set minimum osx build target, now is 10.14, which is the same as the flutter xcode project
        system2(
            f'MACOSX_DEPLOYMENT_TARGET=10.14 cargo build --features {features} --release')
    # copy dylib
    system2(
        "cp target/release/liblibrustdesk.dylib target/release/librustdesk.dylib")
    os.chdir('flutter')
    system2('flutter build macos --release')
    system2('cp -rf ../target/release/service ./build/macos/Build/Products/Release/RustDesk.app/Contents/MacOS/')
    '''
    system2(
        "create-dmg --volname \"RustDesk Installer\" --window-pos 200 120 --window-size 800 400 --icon-size 100 --app-drop-link 600 185 --icon RustDesk.app 200 190 --hide-extension RustDesk.app rustdesk.dmg ./build/macos/Build/Products/Release/RustDesk.app")
    os.rename("rustdesk.dmg", f"../rustdesk-{version}.dmg")
    '''
    os.chdir("..")


def build_flutter_arch_manjaro(version, features):
    if not skip_cargo:
        system2(f'cargo build --features {features} --lib --release')
    ffi_bindgen_function_refactor()
    os.chdir('flutter')
    system2('flutter build linux --release')
    system2(f'strip {flutter_build_dir}/lib/librustdesk.so')
    os.chdir('../res')
    system2('HBB=`pwd`/.. FLUTTER=1 makepkg -f')


def build_flutter_windows(version, features, skip_portable_pack):
    if not skip_cargo:
        # 添加更详细的错误检查
        print("Building Rust library...")
        print(f"Features to build: {features}")
        
        # 清理之前的构建
        if os.path.exists("target/release/deps"):
            print("Cleaning previous build artifacts...")
            shutil.rmtree("target/release/deps", ignore_errors=True)
        
        cargo_result = os.system(f'cargo build --features {features} --lib --release')
        if cargo_result != 0:
            print("cargo build failed, please check rust source code.")
            print("Possible issues:")
            print("1. Missing dependencies")
            print("2. Compilation errors in Rust code")
            print("3. Environment configuration issues")
            exit(-1)
        
        # 检查生成的库文件
        lib_files = [
            "target/release/librustdesk.dll",
            "target/release/deps/librustdesk.dll",
            "target/release/rustdesk.dll"
        ]
        
        lib_found = False
        for lib_file in lib_files:
            if os.path.exists(lib_file):
                print(f"Found Rust library: {lib_file}")
                lib_found = True
                break
        
        if not lib_found:
            print("cargo build completed but library file not found!")
            print("Checking target/release contents:")
            if os.path.exists("target/release"):
                for item in os.listdir("target/release"):
                    print(f"  {item}")
            exit(-1)
    
    # 构建 Flutter 应用
    print("Building Flutter application...")
    os.chdir('flutter')
    flutter_result = os.system('flutter build windows --release --target-platform windows-x64')
    if flutter_result != 0:
        print("Flutter build failed!")
        os.chdir('..')
        exit(-1)
    os.chdir('..')
    
    # 更全面的路径检测 - 确保包含 x64 架构路径
    possible_paths = [
        'flutter/build/windows/x64/runner/Release',
        'flutter/build/windows/runner/x64/Release',
        'flutter/build/windows/runner/Release', 
        'flutter/build/windows/Release',
        'flutter/build/windows/x64/Release'
    ]
    
    flutter_output_dir = None
    for path in possible_paths:
        full_path = os.path.abspath(path)
        print(f"Checking path: {full_path}")
        if os.path.exists(path):
            flutter_output_dir = path
            print(f"Found Flutter output directory: {path}")
            break
    
    if not flutter_output_dir:
        print("Error: Flutter build output directory not found!")
        print("Available directories structure:")
        
        # 显示详细的目录结构
        if os.path.exists('flutter/build'):
            print("flutter/build structure:")
            for root, dirs, files in os.walk('flutter/build'):
                level = root.replace('flutter/build', '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files[:10]:  # 限制文件显示数量
                    print(f"{subindent}{file}")
                if len(files) > 10:
                    print(f"{subindent}... and {len(files)-10} more files")
        else:
            print("flutter/build directory does not exist!")
        exit(-1)
    
    print(f"Using Flutter build output from: {flutter_output_dir}")
    
    # 检查并复制虚拟显示库
    virtual_display_dll = 'target/release/deps/dylib_virtual_display.dll'
    if os.path.exists(virtual_display_dll):
        shutil.copy2(virtual_display_dll, flutter_output_dir)
        print(f"Copied virtual display library to {flutter_output_dir}")
    else:
        print(f"Warning: Virtual display library not found at {virtual_display_dll}")
    
    if skip_portable_pack:
        return
    os.chdir('libs/portable')
    system2('pip3 install -r requirements.txt')
    system2(
        f'python3 ./generate.py -f ../../{flutter_output_dir} -o . -e ../../{flutter_output_dir}/rustdesk.exe')
    os.chdir('../..')
    if os.path.exists('./rustdesk_portable.exe'):
        os.replace('./target/release/rustdesk-portable-packer.exe',
                   './rustdesk_portable.exe')
    else:
        os.rename('./target/release/rustdesk-portable-packer.exe',
                  './rustdesk_portable.exe')
    print(
        f'output location: {os.path.abspath(os.curdir)}/rustdesk_portable.exe')
    os.rename('./rustdesk_portable.exe', f'./rustdesk-{version}-install.exe')
    print(
        f'output location: {os.path.abspath(os.curdir)}/rustdesk-{version}-install.exe')


def check_build_environment():
    """检查构建环境是否正确配置"""
    print("Checking build environment...")
    
    # 检查必要的工具
    required_tools = []
    if windows:
        required_tools = ['cargo', 'python3', 'flutter']
    else:
        required_tools = ['cargo', 'python3', 'flutter', 'gcc', 'pkg-config']
    
    missing_tools = []
    for tool in required_tools:
        if shutil.which(tool) is None:
            missing_tools.append(tool)
    
    if missing_tools:
        print(f"Error: Missing required tools: {', '.join(missing_tools)}")
        return False
    
    # 检查 Rust 工具链
    try:
        result = os.system('cargo --version')
        if result != 0:
            print("Error: Cargo is not working properly")
            return False
    except:
        print("Error: Failed to check cargo version")
        return False
    
    # 检查 Flutter
    try:
        result = os.system('flutter doctor --android-licenses')
        # Flutter doctor 可能返回非零值但仍然可用，所以不严格检查
    except:
        print("Warning: Flutter doctor check failed, but continuing...")
    
    print("Build environment check completed")
    return True

def main():
    global skip_cargo
    
    # 检查构建环境
    if not check_build_environment():
        sys.exit(-1)
    
    parser = make_parser()
    args = parser.parse_args()

    if os.path.exists(exe_path):
        os.unlink(exe_path)
    if os.path.isfile('/usr/bin/pacman'):
        system2('git checkout src/ui/common.tis')
    version = get_version()
    features = ','.join(get_features(args))
    flutter = args.flutter
    if not flutter:
        system2('python3 res/inline-sciter.py')
    print(f"Skip cargo: {args.skip_cargo}")
    if args.skip_cargo:
        skip_cargo = True
    portable = args.portable
    package = args.package
    if package:
        build_deb_from_folder(version, package)
        return
    res_dir = 'resources'
    external_resources(flutter, args, res_dir)
    if windows:
        # build virtual display dynamic library
        os.chdir('libs/virtual_display/dylib')
        system2('cargo build --release')
        os.chdir('../../..')

        if flutter:
            build_flutter_windows(version, features, args.skip_portable_pack)
            return
        system2('cargo build --release --features ' + features)
        # system2('upx.exe target/release/rustdesk.exe')
        system2('mv target/release/rustdesk.exe target/release/RustDesk.exe')
        pa = os.environ.get('P')
        if pa:
            # https://certera.com/kb/tutorial-guide-for-safenet-authentication-client-for-code-signing/
            system2(
                f'signtool sign /a /v /p {pa} /debug /f .\\cert.pfx /t http://timestamp.digicert.com  '
                'target\\release\\rustdesk.exe')
        else:
            print('Not signed')
        system2(
            f'cp -rf target/release/RustDesk.exe {res_dir}')
        os.chdir('libs/portable')
        system2('pip3 install -r requirements.txt')
        system2(
            f'python3 ./generate.py -f ../../{res_dir} -o . -e ../../{res_dir}/rustdesk-{version}-win7-install.exe')
        system2('mv ../../{res_dir}/rustdesk-{version}-win7-install.exe ../..')
    # 注释掉Linux发行版构建逻辑，dev环境只构建Windows包
    # elif os.path.isfile('/usr/bin/pacman'):
    #     # pacman -S -needed base-devel
    #     system2("sed -i 's/pkgver=.*/pkgver=%s/g' res/PKGBUILD" % version)
    #     if flutter:
    #         build_flutter_arch_manjaro(version, features)
    #     else:
    #         system2('cargo build --release --features ' + features)
    #         system2('git checkout src/ui/common.tis')
    #         system2('strip target/release/rustdesk')
    #         system2('ln -s res/pacman_install && ln -s res/PKGBUILD')
    #         system2('HBB=`pwd` makepkg -f')
    #     system2('mv rustdesk-%s-0-x86_64.pkg.tar.zst rustdesk-%s-manjaro-arch.pkg.tar.zst' % (
    #         version, version))
    #     # pacman -U ./rustdesk.pkg.tar.zst
    # elif os.path.isfile('/usr/bin/yum'):
    #     system2('cargo build --release --features ' + features)
    #     system2('strip target/release/rustdesk')
    #     system2(
    #         "sed -i 's/Version:    .*/Version:    %s/g' res/rpm.spec" % version)
    #     system2('HBB=`pwd` rpmbuild -ba res/rpm.spec')
    #     system2(
    #         'mv $HOME/rpmbuild/RPMS/x86_64/rustdesk-%s-0.x86_64.rpm ./rustdesk-%s-fedora28-centos8.rpm' % (
    #             version, version))
    #     # yum localinstall rustdesk.rpm
    # elif os.path.isfile('/usr/bin/zypper'):
    #     system2('cargo build --release --features ' + features)
    #     system2('strip target/release/rustdesk')
    #     system2(
    #         "sed -i 's/Version:    .*/Version:    %s/g' res/rpm-suse.spec" % version)
    #     system2('HBB=`pwd` rpmbuild -ba res/rpm-suse.spec')
    #     system2(
    #         'mv $HOME/rpmbuild/RPMS/x86_64/rustdesk-%s-0.x86_64.rpm ./rustdesk-%s-suse.rpm' % (
    #             version, version))
    #     # yum localinstall rustdesk.rpm
    # 注释掉非Windows构建逻辑，dev环境只构建Windows包
    # else:
    #     if flutter:
    #         if osx:
    #             build_flutter_dmg(version, features)
    #             pass
    #         else:
    #             # system2(
    #             #     'mv target/release/bundle/deb/rustdesk*.deb ./flutter/rustdesk.deb')
    #             build_flutter_deb(version, features)
    #     else:
    #         system2('cargo bundle --release --features ' + features)
    #         if osx:
    #             system2(
    #                 'strip target/release/bundle/osx/RustDesk.app/Contents/MacOS/rustdesk')
    #             system2(
    #                 'cp libsciter.dylib target/release/bundle/osx/RustDesk.app/Contents/MacOS/')
    #             # https://github.com/sindresorhus/create-dmg
    #             system2('/bin/rm -rf *.dmg')
    #             pa = os.environ.get('P')
    #             if pa:
    #                 system2('''
    # # buggy: rcodesign sign ... path/*, have to sign one by one
    # # install rcodesign via cargo install apple-codesign
    # #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/rustdesk
    # #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/libsciter.dylib
    # #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./target/release/bundle/osx/RustDesk.app
    # # goto "Keychain Access" -> "My Certificates" for below id which starts with "Developer ID Application:"
    # codesign -s "Developer ID Application: {0}" --force --options runtime  ./target/release/bundle/osx/RustDesk.app/Contents/MacOS/*
    # codesign -s "Developer ID Application: {0}" --force --options runtime  ./target/release/bundle/osx/RustDesk.app
    # '''.format(pa))
    #             system2(
    #                 'create-dmg "RustDesk %s.dmg" "target/release/bundle/osx/RustDesk.app"' % version)
    #             os.rename('RustDesk %s.dmg' %
    #                       version, 'rustdesk-%s.dmg' % version)
    #             if pa:
    #                 system2('''
    # # https://pyoxidizer.readthedocs.io/en/apple-codesign-0.14.0/apple_codesign.html
    # # https://pyoxidizer.readthedocs.io/en/stable/tugger_code_signing.html
    # # https://developer.apple.com/developer-id/
    # # goto xcode and login with apple id, manager certificates (Developer ID Application and/or Developer ID Installer) online there (only download and double click (install) cer file can not export p12 because no private key)
    # #rcodesign sign --p12-file ~/.p12/rustdesk-developer-id.p12 --p12-password-file ~/.p12/.cert-pass --code-signature-flags runtime ./rustdesk-{1}.dmg
    # codesign -s "Developer ID Application: {0}" --force --options runtime ./rustdesk-{1}.dmg
    # # https://appstoreconnect.apple.com/access/api
    # # https://gregoryszorc.com/docs/apple-codesign/stable/apple_codesign_getting_started.html#apple-codesign-app-store-connect-api-key
    # # p8 file is generated when you generate api key (can download only once)
    # rcodesign notary-submit --api-key-path ../.p12/api-key.json  --staple rustdesk-{1}.dmg
    # # verify:  spctl -a -t exec -v /Applications/RustDesk.app
    # '''.format(pa, version))
    #             else:
    #                 print('Not signed')
    #         else:
    #             # build deb package
    #             system2(
    #                 'mv target/release/bundle/deb/rustdesk*.deb ./rustdesk.deb')
    #             system2('dpkg-deb -R rustdesk.deb tmpdeb')
    #             system2('mkdir -p tmpdeb/usr/share/rustdesk/files/systemd/')
    #             system2('mkdir -p tmpdeb/usr/share/icons/hicolor/256x256/apps/')
    #             system2('mkdir -p tmpdeb/usr/share/icons/hicolor/scalable/apps/')
    #             system2(
    #                 'cp res/rustdesk.service tmpdeb/usr/share/rustdesk/files/systemd/')
    #             system2(
    #                 'cp res/128x128@2x.png tmpdeb/usr/share/icons/hicolor/256x256/apps/rustdesk.png')
    #             system2(
    #                 'cp res/scalable.svg tmpdeb/usr/share/icons/hicolor/scalable/apps/rustdesk.svg')
    #             system2(
    #                 'cp res/rustdesk.desktop tmpdeb/usr/share/applications/rustdesk.desktop')
    #             system2(
    #                 'cp res/rustdesk-link.desktop tmpdeb/usr/share/applications/rustdesk-link.desktop')
    #             os.system('mkdir -p tmpdeb/etc/rustdesk/')
    #             os.system('cp -a res/startwm.sh tmpdeb/etc/rustdesk/')
    #             os.system('mkdir -p tmpdeb/etc/X11/rustdesk/')
    #             os.system('cp res/xorg.conf tmpdeb/etc/X11/rustdesk/')
    #             os.system('cp -a DEBIAN/* tmpdeb/DEBIAN/')
    #             os.system('mkdir -p tmpdeb/etc/pam.d/')
    #             os.system('cp pam.d/rustdesk.debian tmpdeb/etc/pam.d/rustdesk')
    #             system2('strip tmpdeb/usr/bin/rustdesk')
    #             system2('mkdir -p tmpdeb/usr/share/rustdesk')
    #             system2('mv tmpdeb/usr/bin/rustdesk tmpdeb/usr/share/rustdesk/')
    #             system2('cp libsciter-gtk.so tmpdeb/usr/share/rustdesk/')
    #             md5_file_folder("tmpdeb/")
    #             system2('dpkg-deb -b tmpdeb rustdesk.deb; /bin/rm -rf tmpdeb/')
    #             os.rename('rustdesk.deb', 'rustdesk-%s.deb' % version)
    else:
        print("Dev environment: Only Windows build is supported. Please use Windows for development.")
        sys.exit(-1)


def md5_file(fn):
    md5 = hashlib.md5(open('tmpdeb/' + fn, 'rb').read()).hexdigest()
    system2('echo "%s  /%s" >> tmpdeb/DEBIAN/md5sums' % (md5, fn))

def md5_file_folder(base_dir):
    base_path = Path(base_dir)
    for file in base_path.rglob('*'):
        if file.is_file() and 'DEBIAN' not in file.parts:
            relative_path = file.relative_to(base_path)
            md5_file(str(relative_path))


if __name__ == "__main__":
    main()
