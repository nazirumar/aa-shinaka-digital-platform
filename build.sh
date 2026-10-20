#!/usr/bin/env bash
#
# Render build script (native Python runtime).
#
# Render runs this from the repository root on every deploy, BEFORE the start
# command. It must produce a complete, verifiable set of production static
# files, because `config.settings.prod` serves them through WhiteNoise's
# `CompressedManifestStaticFilesStorage`: if `staticfiles/staticfiles.json` is
# missing or has no entry for `css/app.css`, every page that uses
# `{% static %}` raises `ValueError: Missing staticfiles manifest entry`
# and returns HTTP 500.
#
# The script is deliberately strict (`set -euo pipefail`) and verifies its own
# outputs, so a broken build fails here instead of at request time.
#
# Usage:
#   ./build.sh              # normal Render build (installs deps)
#   SKIP_PYTHON_INSTALL=1 ./build.sh   # deps already installed (e.g. Docker)
#   SKIP_NPM_INSTALL=1 ./build.sh      # node_modules already present
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Reach for python3 before python: Render's native runtime provides python3.
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
CARGO_CSS="static/css/app.css"
MANIFEST="staticfiles/staticfiles.json"

echo "[build] Repository: $ROOT_DIR"
echo "[build] Python:     $PYTHON ($("$PYTHON" --version 2>&1))"

# ---------------------------------------------------------------------------
# 1. Python dependencies
# ---------------------------------------------------------------------------
if [ "${SKIP_PYTHON_INSTALL:-0}" != "1" ]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "[build] uv not found; installing it..."
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install uv
  fi
  echo "[build] Installing Python dependencies (uv sync, no dev group)..."
  uv sync --frozen --no-dev
fi

# ---------------------------------------------------------------------------
# 2. Front-end dependencies (Node is present in Render's native runtimes)
# ---------------------------------------------------------------------------
if [ "${SKIP_NPM_INSTALL:-0}" != "1" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "[build] ERROR: npm is required to compile Tailwind CSS but was not found." >&2
    echo "[build]        Render's native runtimes include Node/npm; a Docker build" >&2
    echo "[build]        uses the assets stage in deploy/Dockerfile instead." >&2
    exit 1
  fi
  echo "[build] Installing Node dependencies (npm ci)..."
  npm ci --no-audit --no-fund
fi

# ---------------------------------------------------------------------------
# 3. Compile Tailwind CSS -> static/css/app.css
# ---------------------------------------------------------------------------
echo "[build] Compiling Tailwind CSS..."
npm run build:css

if [ ! -s "$CARGO_CSS" ]; then
  echo "[build] ERROR: expected compiled stylesheet at $CARGO_CSS (missing or empty)." >&2
  exit 1
fi
echo "[build] OK: $CARGO_CSS ($(wc -c <"$CARGO_CSS") bytes)"

# ---------------------------------------------------------------------------
# 4. Collect static files with production settings (WhiteNoise manifest)
# ---------------------------------------------------------------------------
echo "[build] Collecting static files (DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings.prod})..."
DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}" \
  "$PYTHON" manage.py collectstatic --noinput

if [ ! -s "$MANIFEST" ]; then
  echo "[build] ERROR: $MANIFEST was not generated." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 5. Verify the manifest actually contains the stylesheet the templates use
# ---------------------------------------------------------------------------
"$PYTHON" - "$MANIFEST" <<'PY'
import json
import sys

manifest_path = sys.argv[1]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)

paths = manifest.get("paths", {})
required = ("css/app.css",)
missing = [name for name in required if name not in paths]
if missing:
    raise SystemExit(
        f"ERROR: {manifest_path} is missing manifest entries for {missing}. "
        f"Templates using {{% static %}} would raise at request time."
    )

print(f"[build] OK: manifest has {len(paths)} entries; css/app.css -> {paths['css/app.css']}")
PY

echo "[build] Build complete."
