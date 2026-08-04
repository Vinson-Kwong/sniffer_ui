#!/usr/bin/env bash
set -Eeuo pipefail

# Always build from the project root, regardless of where this script is called.
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python}"
EXE_PATH="dist/sniffer_ui.exe"

echo "[1/3] Installing build dependencies..."
"$PYTHON" -m pip install -r requirements-dev.txt

echo "[2/3] Building sniffer_ui.exe..."
"$PYTHON" -m PyInstaller --noconfirm --clean sniffer_ui.spec

echo "[3/3] Checking build output..."
if [[ ! -f "$EXE_PATH" ]]; then
    echo "Build failed: $EXE_PATH was not generated." >&2
    exit 1
fi

echo "Build completed: $EXE_PATH"
