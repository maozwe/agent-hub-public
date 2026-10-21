"""Build a local preview installer; never publishes or creates a release tag."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', required=True, help='Path to Inno Setup ISCC.exe')
    args = parser.parse_args()
    version = json.loads((ROOT / 'version.json').read_text(encoding='utf-8'))['version']
    build = ROOT / 'windows' / 'build'
    build.mkdir(parents=True, exist_ok=True)
    numbers = tuple(int(n) for n in version.split('.')) + (0,)
    info = build / 'version.txt'
    info.write_text(f"VSVersionInfo(ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('FileDescription','Agent Hub'), StringStruct('FileVersion','{version}'), StringStruct('ProductName','Agent Hub'), StringStruct('ProductVersion','{version}')])]), VarFileInfo([VarStruct('Translation',[1033,1200])])])", encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--name', 'AgentHub',
        '--distpath', str(ROOT / 'dist'), '--workpath', str(build / 'pyinstaller'), '--specpath', str(build),
        '--version-file', str(info), '--add-data', f'{ROOT / "version.json"};.',
        '--add-data', f'{ROOT / "web"};web', '--add-data', f'{ROOT / "windows" / "toast.ps1"};windows',
        '--collect-data', 'certifi', str(ROOT / 'desktop.py')], cwd=ROOT, check=True)
    subprocess.run([args.iscc, '/DAppVersion=' + version, str(ROOT / 'windows' / 'installer.iss')], check=True)


if __name__ == '__main__': main()
