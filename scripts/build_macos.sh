#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt 'pyinstaller==6.22.3'
.venv/bin/pyinstaller --noconfirm --clean Stove.spec
codesign --force --deep --sign - dist/Stove.app
DMG_ROOT="$(mktemp -d)"
ditto dist/Stove.app "$DMG_ROOT/Stove.app"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create -volname Stove -fs HFS+ -srcfolder "$DMG_ROOT" -ov -format UDZO dist/Stove-0.2.0-macos-arm64.dmg
