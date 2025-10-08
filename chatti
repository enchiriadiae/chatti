#!/usr/bin/env bash
# chatti-go — launcher for the Chatti TUI
# Usage:
#   ./chatti-go [args...]
# Notes:
#   - Creates a local venv at ./.venv if missing
#   - Installs requirements.txt if present
#   - Executes scripts.chatti_go with all passed arguments

# --- Strict mode -------------------------------------------------------------
# -e: abort on errors, -u: undefined vars => error, pipefail: catch pipe errors
set -euo pipefail

# Optional debug: CHATTI_DEBUG=1 ./chatti-go
if [[ "${CHATTI_DEBUG:-0}" == "1" ]]; then
  set -x
fi

# Optional tighter default permissions for created files (pip caches etc.)
# umask 077

# --- Resolve project root ----------------------------------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Find a usable Python ----------------------------------------------------
# Allow override: CHATTIPY=/path/to/python ./chatti-go
PYBIN="${CHATTIPY:-}"
if [[ -z "$PYBIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYBIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYBIN="python"
  else
    echo "❌ No 'python3' or 'python' found in PATH." >&2
    echo "   Please install Python 3.12+ and retry." >&2
    exit 127
  fi
fi

# --- Ensure venv exists ------------------------------------------------------
if [[ ! -d "$ROOT/.venv" ]]; then
  echo "🐍 No .venv found in $ROOT — creating one..."
  # Some distros require python3-venv, handle that gracefully
  if ! "$PYBIN" -m venv "$ROOT/.venv" 2>/dev/null; then
    echo "⚠️  Failed to create venv. On Debian/Ubuntu: sudo apt install python3-venv" >&2
    # retry once to show the actual error
    "$PYBIN" -m venv "$ROOT/.venv"
  fi

  # Upgrade pip toolchain using the venv interpreter explicitly
  "$ROOT/.venv/bin/python" -m pip install --upgrade pip setuptools wheel

  # Install deps if requirements.txt is present
  if [[ -f "$ROOT/requirements.txt" ]]; then
    echo "📦 Installing requirements.txt…"
    "$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
  fi
fi

# --- Run the launcher inside venv -------------------------------------------
# PYTHONUTF8=1 helps avoid locale/encoding weirdness on some systems
export PYTHONUTF8=1
exec "$ROOT/.venv/bin/python" -m scripts.chatti_go "$@"
