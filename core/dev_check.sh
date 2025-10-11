#!/usr/bin/env bash
# dev_check.sh — Lint, Format, Smoke-Test for Chatti
# Usage:
#   ./scripts/dev_check.sh
#   CI=1 ./scripts/dev_check.sh        # quieter output for CI
#
# Requires: ruff, bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

quiet() {
  if [[ "${CI:-0}" == "1" ]]; then
    "$@" >/dev/null 2>&1 || return $?
  else
    "$@"
  fi
}

echo "== Ruff version =="
quiet ruff --version || { echo "Ruff not found. Install with: pip install ruff"; exit 1; }

echo "== Ruff check (focused rules) =="
# Only logic-relevant rules (no cosmetic noise)
quiet ruff check . --select F401,F821,F841,ARG,UP --fix

echo "== Ruff format =="
quiet ruff format .

echo "== Release smoke test =="
if [[ -x "scripts/release_smoke.sh" ]]; then
  quiet bash scripts/release_smoke.sh
else
  echo "(skip) scripts/release_smoke.sh not found or not executable"
fi

echo "== Done =="
