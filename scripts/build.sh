#!/usr/bin/env bash
# Build phase: generate the protobuf/gRPC surface for this primitive.
#
# The package has no ROS packages and no Docker image — it is a native
# Python process that speaks TCP to the PLC. The only build-time concern
# is `rbnx codegen`.
set -euo pipefail
PKG="${RBNX_PACKAGE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ROOT="${RBNX_DEPLOY_ROOT:-$(cd "$PKG/../../.." && pwd)}"
if [[ ! -f "$ROOT/scripts/uv_sync.sh" ]]; then
    echo "[cartesian_plotter/build] ERR: deployment root not found at $ROOT (missing scripts/uv_sync.sh) — build this package from its rbnx deployment, or set RBNX_DEPLOY_ROOT." >&2
    exit 2
fi
cd "$PKG"

CLEAN="${RBNX_BUILD_CLEAN:-}"
if [[ "$CLEAN" == "1" ]]; then
    echo "[cartesian_plotter/build] clean: removing rbnx-build/"
    rm -rf rbnx-build
fi
mkdir -p rbnx-build

# Deployment-wide uv environment (shared by the primitive and both skills).
bash "$ROOT/scripts/uv_sync.sh"

# Generate with the deployment venv so the gencode matches the grpcio/protobuf
# pins that start.sh runs with (see pyproject.toml).
export RBNX_CODEGEN_PYTHON="$ROOT/.venv/bin/python"

FLAGS=(--out-dir "$PKG/rbnx-build/codegen" --mcp)
[[ "$CLEAN" == "1" ]] && FLAGS+=(--clean)

echo "[cartesian_plotter/build] rbnx codegen ${FLAGS[*]}"
rbnx codegen -p "$PKG" "${FLAGS[@]}"

touch "$PKG/rbnx-build/.rbnx-built"
echo "[cartesian_plotter/build] done."