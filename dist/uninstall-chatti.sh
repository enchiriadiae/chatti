#!/usr/bin/env bash
# Shebang: Nimm die Bash aus der Umgebung (z.B. /usr/bin/bash oder /bin/bash)

set -euo pipefail
# -e  = Script bricht bei erstem Fehler ab (Exit-Code != 0)
# -u  = Verwendung nicht gesetzter Variablen ist ein Fehler
# -o pipefail = wenn ein Befehl in einer Pipe fehlschlägt, zählt das als Fehler

#####################################################################
#####################################################################
#
# uninstall-chatti.sh
#
# Voraussetzung: Python 3.12 oder höher
# Im Archiv sollten folgende Dateien liegen:
#       chatti_client-0.9.1-py3-none-any.whl
#       install-chatti.sh
#       uninstall-chatti.sh
#       README.txt
#
# Keine Admin-Recht nötig.
# Das Script löscht ausschließlich lokale Daten in $HOME-Umgebung.
#
# Was macht das Script?
# --------------------
# Entfernt den ChatGPT-Clienten Chatti aus dem System.
# Gelöscht wird:
#       - die virtuelle Umgebung, die install-chatti.sh angelegt hat.
#           👉🏽 Hinweis: Nach weiteren Umgebungen wird nicht gesucht.
#              Installationen, die nicht über install-chatti.sh gelaufen sind, kannst du manuell löschen.
#       - das Startscript in ~./bin (sofern vorhanden)
#
# Abschluss mit Hinweis auf Chatti im $PATH
# User-spezifische Verzeichnisse bleiben unangetastet!
#
#####################################################################
#####################################################################

echo ">>> Chatti-Deinstallation"

# 1) Wheel-/venv-Installationspfad
# ----------------------------------------------------
# VENV_DIR ist der Ordner, in den das Install-Skript die
# virtuelle Umgebung für Chatti gelegt hat.
# Beispiel hier:
#   /home/<USER>/.local/share/chatti-venv
VENV_DIR="$HOME/.local/share/chatti-venv"

# WRAPPER ist die kleine Startdatei, die wir optional unter
# ~/bin/chatti angelegt haben.
# Der Zweck: User tippt nur noch "chatti" und nicht mehr den langen Pfad.
WRAPPER="$HOME/bin/chatti"

# 2) In venv installierte Pakete entfernen
# ----------------------------------------------------
if [[ -d "$VENV_DIR" ]]; then
  echo "↪ Entferne Chatti-venv unter: $VENV_DIR"

  # Versuch, in der venv explizit das Paket 'chatti-client' zu deinstallieren.
  # Falls das aus irgendeinem Grund fehlschlägt (z.B. pip kaputt),
  # sorgt '|| true' dafür, dass das Script trotzdem weiterläuft.
  "$VENV_DIR/bin/python" -m pip uninstall -y chatti-client || true

  # Danach wird die komplette virtuelle Umgebung gelöscht.
  # Das schließt alle für Chatti installierten Dependencies mit ein.
  rm -rf "$VENV_DIR"
  echo "   ✅ venv gelöscht."
else
  # Falls die venv nicht existiert, geben wir nur eine Info aus.
  echo "ℹ️  Keine Chatti-venv unter $VENV_DIR gefunden."
fi

# 3) Wrapper-Skript unter ~/bin entfernen (falls vorhanden)
# ----------------------------------------------------
# Hier prüfen wir, ob die Startdatei ~/bin/chatti existiert.
if [[ -f "$WRAPPER" ]]; then
  echo "   → Gefundene Startdatei: $WRAPPER"
  echo -n "   Diese Startdatei löschen? [y/N] "
  # read -r REPLY_WRAP:
  #   - liest eine Zeile von der Tastatur
  #   - speichert sie in der Variablen REPLY_WRAP
  #   - -r bedeutet: Backslashes nicht als Escapezeichen behandeln
  read -r REPLY_WRAP

  case "$REPLY_WRAP" in
    # y, Y, j, J + beliebiger Rest (Enter, bla bla, etc.)
    [yYjJ]*)
      # Startdatei löschen
      rm -f "$WRAPPER"
      echo "   ✅ Startdatei gelöscht."
      ;;
    *)
      # Alles andere: Datei bleibt erhalten
      echo "   → Startdatei bleibt erhalten."
      ;;
  esac
else
  # Kein Wrapper gefunden -> Info.
  echo "ℹ️  Keine Startdatei ~/bin/chatti gefunden."
fi

# 4) PATH-Eintrag in Shell-RCs optional entfernen
# ----------------------------------------------------
# Wir fassen die PATH-Bereinigung NICHT automatisch an, sondern
# geben nur einen Hinweis, falls noch ein Chatti-Eintrag drin ist.
# Hintergrund:
#   - ~/.bashrc und ~/.zshrc können sehr individuell sein
#   - Automatisches "rausschneiden" kann hässlich werden
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
  # Falls die Datei nicht existiert: Überspringen
  [ -f "$rc" ] || continue

  # grep -Fq:   F = wortwörtlich suchen (keine Regex),
  #             q = ruhig, d.h. nur Rückgabecode, keine Ausgabe
  if grep -Fq 'Chatti: CLI im PATH verfügbar machen' "$rc"; then
    echo "   → Hinweis: In $rc existiert noch ein Chatti-PATH-Eintrag."
    echo "     Du kannst ihn bei Bedarf manuell entfernen:"
    echo "       # Chatti: CLI im PATH verfügbar machen"
    echo "       export PATH=\"\$HOME/.local/share/chatti-venv/bin:\$PATH\""
  fi
done

echo
echo
echo "✅ Deinstallation abgeschlossen."
echo
echo "ℹ️  Hinweis:"
echo "   Die persönlichen Chatti-Daten (Konfiguration, Chat-Historie, Anhänge)"
echo "   wurden NICHT gelöscht. Wenn du wirklich alles entfernen willst, kannst du"
echo "   diese Verzeichnisse manuell löschen:"
echo "     $HOME/.config/chatti-cli"
echo "     $HOME/.local/share/chatti-cli"