#!/usr/bin/env bash
# Build the self-contained Linux bundle: dist/coolbar-linux-x64.tar.gz
# Requires the project venv (python3-gobject visible via --system-site-packages) with pyinstaller.
set -euo pipefail
cd "$(dirname "$0")/../.."
PY="${PY:-.venv/bin/python}"
VERSION="${1:-$(git describe --tags --always 2>/dev/null || echo dev)}"

printf 'from coolbar.app import main\n\nraise SystemExit(main())\n' > run_coolbar.py
"$PY" -m PyInstaller -y --clean --noconfirm \
  --name coolbar --noconsole --paths . \
  --collect-all bleak --collect-all dbus_next --collect-submodules coolbar \
  --distpath dist/pyi --workpath build/pyi --specpath build \
  run_coolbar.py

cp packaging/linux/coolbar.svg dist/pyi/coolbar/
printf '%s\n' "$VERSION" > dist/pyi/coolbar/VERSION
tar -czf "dist/coolbar-linux-x64.tar.gz" -C dist/pyi coolbar
cp packaging/linux/install.sh dist/install.sh
echo "built dist/coolbar-linux-x64.tar.gz ($VERSION)"
