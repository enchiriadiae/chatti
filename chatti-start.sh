#!/usr/bin/env bash


# -----------------------------------------------------------------------------
# README (macOS / Linux) — chatti-start.sh
#
# Start (im Projektordner):
#   chmod +x ./chatti-start.sh
#   ./chatti-start.sh
#
# Optional: bestimmtes Python erzwingen (z.B. Homebrew/pyenv):
#   CHATTIPY=/opt/homebrew/bin/python3.13 ./chatti-start.sh
#   # oder allgemein:
#   CHATTIPY="$(command -v python3)" ./chatti-start.sh
#
# Debug-Ausgabe:
#   CHATTI_DEBUG=1 ./chatti-start.sh
#
# Hinweis zu sudo:
#   Den Launcher normalerweise OHNE sudo starten.
#   Wenn du wirklich Root brauchst, Environment explizit durchreichen:
#     sudo env CHATTIPY=/opt/homebrew/bin/python3.13 ./chatti-start.sh
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# README (macOS / Linux) — chatti-start.sh
#
# Start (im Projektordner):
#   chmod +x ./chatti-start.sh
#   ./chatti-start.sh
#
# Optional: bestimmtes Python erzwingen (z.B. Homebrew/pyenv):
#   CHATTIPY=/opt/homebrew/bin/python3.13 ./chatti-start.sh
#   # oder allgemein:
#   CHATTIPY="$(command -v python3)" ./chatti-start.sh
#
# Debug-Ausgabe:
#   CHATTI_DEBUG=1 ./chatti-start.sh
#
# Hinweis zu sudo:
#   Den Launcher normalerweise OHNE sudo starten.
#   Wenn du wirklich Root brauchst, Environment explizit durchreichen:
#     sudo env CHATTIPY=/opt/homebrew/bin/python3.13 ./chatti-start.sh
# -----------------------------------------------------------------------------


# chatti-start.sh — launcher for the Chatti TUI (macOS/Linux)
#
# Usage:
#   ./chatti-start.sh [args...]
#
# Optional:
#   CHATTIPY=/path/to/python ./chatti-start.sh
#   CHATTI_DEBUG=1 ./chatti-start.sh

set -euo pipefail
[[ "${CHATTI_DEBUG:-0}" == "1" ]] && set -x

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"

die() { echo "❌ $*" >&2; exit 1; }
log() { echo "$*"; }

hash_file() {
  local f="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$f" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  else
    return 1
  fi
}

pick_python() {
  if [[ -n "${CHATTIPY:-}" ]]; then
    [[ -x "$CHATTIPY" ]] || die "CHATTIPY is set but not executable: $CHATTIPY"
    echo "$CHATTIPY"; return 0
  fi

  # Prefer common Homebrew paths on macOS, but harmless elsewhere.
  local candidates=(
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3"
  )
  for c in "${candidates[@]}"; do
    [[ -x "$c" ]] && { echo "$c"; return 0; }
  done

  command -v python3 >/dev/null 2>&1 && { echo "python3"; return 0; }
  command -v python  >/dev/null 2>&1 && { echo "python";  return 0; }

  die "No 'python3' or 'python' found. Install Python 3.12+."
}

version_ok() {
  local py="$1"
  local pyver
  pyver="$("$py" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  local major="${pyver%%.*}"
  local minor="${pyver#*.}"

  if [[ "$major" -lt 3 ]] || { [[ "$major" -eq 3 ]] && [[ "$minor" -lt 12 ]]; }; then
    die "Gefundene Python-Version ist $pyver (via: $py) – benötigt wird mindestens 3.12."
  fi
}

ensure_venv() {
  local py="$1"

  if [[ ! -d "$VENV_DIR" ]]; then
    log "🐍 No .venv found — creating one with: $py"
    "$py" -m venv "$VENV_DIR"
  fi

  if [[ ! -x "$VENV_PY" ]]; then
    log "⚠️  .venv seems broken — recreating…"
    rm -rf "$VENV_DIR"
    "$py" -m venv "$VENV_DIR"
  fi

  "$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null
}

install_requirements_if_needed() {
  local req_file="$ROOT/requirements.txt"
  local stamp="$VENV_DIR/.requirements.stamp"

  [[ -f "$req_file" ]] || return 0

  local new_hash old_hash=""
  new_hash="$(hash_file "$req_file" || true)"
  [[ -n "$new_hash" ]] || die "No shasum/sha256sum available to hash requirements.txt"

  [[ -f "$stamp" ]] && old_hash="$(cat "$stamp" 2>/dev/null || true)"

  if [[ "$new_hash" != "$old_hash" ]]; then
    log "📦 Installing requirements.txt (changed)…"
    "$VENV_PY" -m pip install -r "$req_file"
    printf '%s' "$new_hash" > "$stamp"
  fi
}

PYBIN="$(pick_python)"
version_ok "$PYBIN"
ensure_venv "$PYBIN"
install_requirements_if_needed

export PYTHONUTF8=1
exec "$VENV_PY" -m scripts.chatti_go "$@"
