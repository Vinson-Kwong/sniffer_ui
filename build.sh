#!/usr/bin/env bash
set -Eeuo pipefail

# Always build from the project root, regardless of where this script is called.
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python}"
EXE_PATH="dist/sniffer_ui.exe"

if [[ ! -d merge_app/src ]]; then
    echo "merge_app/src (mocap_merge source) is required: the BVH merge runs bundled in-process." >&2
    echo "Clone it first: git clone git@github.com:Vinson-Kwong/mocap_merge.git merge_app/src" >&2
    exit 1
fi

echo "[1/4] Installing build dependencies..."
"$PYTHON" -m pip install -r requirements-dev.txt

echo "[2/4] Installing mocap_merge (bundled into the exe for the BVH merge)..."
"$PYTHON" -m pip install -e merge_app/src

echo "[3/4] Building sniffer_ui.exe..."
"$PYTHON" -m PyInstaller --noconfirm --clean sniffer_ui.spec

echo "[4/4] Checking build output..."
if [[ ! -f "$EXE_PATH" ]]; then
    echo "Build failed: $EXE_PATH was not generated." >&2
    exit 1
fi

echo "Build completed: $EXE_PATH"
