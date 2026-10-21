# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH)
ASSETS = [(str(ROOT / 'stove' / name), '.') for name in ('index.html', 'style.css', 'tracks.json')]

a = Analysis(
    [str(ROOT / 'stove' / 'app.py')],
    pathex=[str(ROOT / 'stove')],
    binaries=[],
    datas=ASSETS,
    hiddenimports=['AppKit', 'Foundation', 'CoreBluetooth', 'WebKit', 'objc', 'PyObjCTools.AppHelper', 'bleak.backends.corebluetooth'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Stove', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Stove')
app = BUNDLE(
    coll,
    name='Stove.app',
    icon=str(ROOT / 'assets' / 'Stove.icns'),
    bundle_identifier='dev.stove.watch',
    info_plist={
        'CFBundleDisplayName': 'Stove',
        'CFBundleShortVersionString': '0.2.0',
        'CFBundleVersion': '2',
        'LSMinimumSystemVersion': '13.0',
        'NSBluetoothAlwaysUsageDescription': 'Stove connects to your CMF Watch 3 Pro to control this Mac.',
    },
)
