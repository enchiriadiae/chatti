#!/usr/bin/env bash
set -euo pipefail

PAGE="${1:-docs/man1/chatti.1}"
MANUAL="docs/MANUAL.md"

if [[ ! -f "$PAGE" ]]; then
  echo "Manpage nicht gefunden: $PAGE" >&2
  exit 1
fi

have() { command -v "$1" >/dev/null 2>&1; }

OS="$(uname -s 2>/dev/null || echo Unknown)"

render_with_mandoc() { mandoc -Tutf8 "$PAGE" | less -R; }
render_with_groff()  { groff -Kutf8 -Tutf8 -man "$PAGE" | less; }
render_with_nroff()  { nroff -man "$PAGE" | col -bx | less -R; }

case "$OS" in
  Darwin*)
    if have mandoc; then render_with_mandoc
    elif have groff; then render_with_groff
    elif have nroff; then render_with_nroff
    else sed -E 's/^\.([A-Z]{1,3}).*//g' "$PAGE" | less -R
    fi
    ;;
  Linux*|*BSD)
    if have mandoc; then render_with_mandoc
    elif have groff; then render_with_groff
    elif have nroff; then render_with_nroff
    else sed -E 's/^\.([A-Z]{1,3}).*//g' "$PAGE" | less -R
    fi
    ;;
  CYGWIN*|MINGW*|MSYS*|Windows_NT)
    # Windows-Fallback: Markdown-Handbuch öffnen
    if [[ -f "$MANUAL" ]]; then
      echo "Kein roff-Renderer gefunden. Oeffne $MANUAL ..."
      if have cmd.exe; then
        cmd.exe /C start "$MANUAL"
      elif have powershell.exe; then
        powershell.exe -NoProfile -Command "Start-Process '$MANUAL'"
      else
        echo "Bitte $MANUAL manuell oeffnen."
      fi
    else
      echo "Weder Renderer noch $MANUAL gefunden. Zeige rohe Textversion:"
      sed -E 's/^\.([A-Z]{1,3}).*//g' "$PAGE"
    fi
    ;;
  *)
    # generischer Fallback
    sed -E 's/^\.([A-Z]{1,3}).*//g' "$PAGE" | less -R
    ;;
esac
