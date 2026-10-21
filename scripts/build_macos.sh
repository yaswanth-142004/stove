#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt 'pyinstaller==6.22.3'
.venv/bin/pyinstaller --noconfirm --clean Stove.spec
codesign --force --deep --sign - dist/Stove.app
mkdir -p dist/dmg-root
cp -R dist/Stove.app dist/dmg-root/
ln -s /Applications dist/dmg-root/Applications
hdiutil create -volname Stove -srcfolder dist/dmg-root -ov -format UDZO dist/Stove-0.1.0-macos-arm64.dmg
