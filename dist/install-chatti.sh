#!/usr/bin/env bash
# Shebang: Nutzt das zuerst gefundene `bash` im PATH

# -e  : Script bricht bei erstem Fehler ab
# -u  : Ungesetzte Variablen als Fehler behandeln
# -o pipefail : Fehler in Pipelines nicht verschlucken
set -euo pipefail

#####################################################################
#####################################################################
#
# install-chatti.sh
# Installations-Script für Chatti, einen Terminal-basierten ChatGPT-Client.
#
# Voraussetzung: Python 3.12 oder höher
# Im Archiv sollten folgende Dateien liegen:
#       chatti_client-0.9.1-py3-none-any.whl
#       install-chatti.sh
#       uninstall-chatti.sh
#       README.txt
#
# Keine Admin-Rechte nötig.
# Das Script schreibt ausschließlich lokale Daten in der $HOME-Umgebung.
#
# Was macht das Script?
# ---------------------
#
# (1) Prüft das Zielsystem auf eine vorhandene Python-Installation (python3 / python)
#     und deren Version. Benötigt wird mindestens Python 3.12.
#     Wenn nicht vorhanden oder zu alt: Abbruch mit Hinweis.
#
# (2) Wenn das Script bereits in einer aktiven virtuellen Umgebung (venv) läuft:
#       → Installiert Chatti direkt in diese venv per:
#         pip install chatti_client-0.9.1-py3-none-any.whl
#       → Danach kann Chatti in genau dieser venv mit „chatti“ gestartet werden.
#
# (3) Wenn KEINE venv aktiv ist, folgt ein Zweig abhängig vom Systemtyp:
#
#     (3a) Prüfung auf PEP-668-Marker („EXTERNALLY-MANAGED“ auf neueren
#          Debian/Ubuntu-Systemen):
#
#          👉🏽 Hinweis:
#          PEP 668 verbietet direkte pip-Installationen in das System-Python.
#          Python selbst wird hier von Debians Paketmanager apt(itude) verwaltet.
#
#          Falls ein solcher Marker gefunden wird:
#            → Es wird eine eigene virtuelle Umgebung nur für Chatti angelegt:
#                 ~/.local/share/chatti-venv
#                 (~/ steht für das Home-Verzeichnis des Users)
#            → In dieser venv werden pip aktualisiert und anschließend
#              Chatti + alle Abhängigkeiten installiert.
#            → Optional:
#                 (4a) Eintrag in ~/.bashrc / ~/.zshrc, um
#                      ~/.local/share/chatti-venv/bin automatisch in $PATH
#                      aufzunehmen.
#                 (4b) Eine kleine Startdatei ~/bin/chatti, mit der sich
#                      Chatti direkt per „chatti“ im Terminal starten lässt.
#
#          Aufruf des Clients in dieser Variante:
#              chatti
#          (nach neuem Terminalstart bzw. mit angepasstem PATH)
#          Alternativ immer möglich:
#              ~/.local/share/chatti-venv/bin/chatti
#
#     (3b) Falls KEIN EXTERNALLY-MANAGED-Marker gefunden wird:
#            → Installation nur für diesen Benutzer mit:
#                 pip install --user chatti_client-0.9.1-py3-none-any.whl
#            → Die Binärdateien landen typischerweise unter:
#                 ~/.local/bin
#            → Chatti lässt sich dann (je nach PATH) so aufrufen:
#                 chatti
#              oder, falls ~/.local/bin nicht im PATH ist, über den
#              vollständigen Pfad.
#
#####################################################################
#####################################################################


echo ">>> Chatti-Installation (Wheel)"

# -------------------------------------------------------------------
# 1) Python finden
# -------------------------------------------------------------------
# `command -v` prüft, ob ein Kommando im PATH auffindbar ist.
# Wir akzeptieren zuerst `python3`, ansonsten fallback auf `python`.
if command -v python3 >/dev/null 2>&1; then
  PYBIN="python3"   # Pfad/Name des Python-Interpreters, der im restlichen Script verwendet wird
elif command -v python >/dev/null 2>&1; then
  PYBIN="python"
else
  echo "❌ Kein Python gefunden."
  echo "   Bitte installiere zuerst Python 3.12 oder neuer:"
  echo "   https://www.python.org/downloads/"
  exit 1
fi

# -------------------------------------------------------------------
# 2) Version prüfen (mindestens 3.12)
# -------------------------------------------------------------------
# Wir rufen den gefundenen Interpreter einmal kurz auf und lassen uns
# Haupt- und Minor-Version ausgeben, z.B. "3.13".
PYVER=$("$PYBIN" - << 'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)

# Gewünschte Mindestversion
REQ_MAJOR=3
REQ_MINOR=12

# MAJOR = alles vor dem ersten Punkt, MINOR = alles nach dem ersten Punkt
# Beispiel: PYVER="3.13" -> MAJOR="3", MINOR="13"
MAJOR=${PYVER%%.*}
MINOR=${PYVER#*.}

# Vergleich: Wenn MAJOR < 3, oder (MAJOR == 3 und MINOR < 12) -> zu alt
if [ "$MAJOR" -lt "$REQ_MAJOR" ] || { [ "$MAJOR" -eq "$REQ_MAJOR" ] && [ "$MINOR" -lt "$REQ_MINOR" ]; }; then
  echo "❌ Gefundene Python-Version ist $PYVER – benötigt wird mindestens 3.12."
  echo "   Bitte aktualisiere Python: https://www.python.org/downloads/"
  exit 1
fi

# -------------------------------------------------------------------
# 3) Wheel lokalisieren (liegt im selben Ordner wie dieses Script)
# -------------------------------------------------------------------
# SCRIPT_DIR = Verzeichnis, in dem dieses Script liegt (nicht das aktuelle Arbeitsverzeichnis!)
#   1. dirname "$0"  -> Verzeichnisname der Script-Datei
#   2. cd dorthin
#   3. pwd -> absoluter Pfad
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"

# WHEEL = Vollständiger Pfad zur Wheel-Datei.
# Erwartung: Wheel und Script liegen im selben Ordner.
WHEEL="${SCRIPT_DIR}/chatti_client-0.9.1-py3-none-any.whl"

# Wenn das Wheel nicht existiert: freundlich abbrechen
if [[ ! -f "$WHEEL" ]]; then
  echo "❌ Konnte Wheel-Datei nicht finden:"
  echo "   $WHEEL"
  echo "   Bitte lege das .whl in dasselbe Verzeichnis wie dieses Script."
  exit 1
fi

# -------------------------------------------------------------------
# 4) Prüfen, ob wir schon in einer venv sind
# -------------------------------------------------------------------
# Idee: In einer venv ist sys.prefix != sys.base_prefix
# Wir geben "1" aus, wenn wir IN einer venv sind, sonst "0".
IN_VENV=$("$PYBIN" - << 'PY'
import sys
print("1" if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else "0")
PY
)

# Fall A: Script wird innerhalb einer bereits aktivierten venv ausgeführt.
# Dann installieren wir einfach in diese venv und sind fertig.
if [[ "$IN_VENV" == "1" ]]; then
  echo "↪ Virtuelle Umgebung erkannt – installiere in die aktive venv …"
  "$PYBIN" -m pip install "$WHEEL"
  echo
  echo "✅ Fertig! Starte Chatti jetzt mit:"
  echo "   chatti --help"
  exit 0
fi

# -------------------------------------------------------------------
# 5) Prüfen, ob das System-Python „extern verwaltet“ ist (PEP 668)
# -------------------------------------------------------------------
# EXTERNALLY_MANAGED:
#   - leerer String  => kein Marker gefunden, System lässt pip in Systempfaden zu
#   - Pfad           => Datei EXTERNALLY-MANAGED gefunden (z.B. /usr/lib/python3.13/EXTERNALLY-MANAGED)
EXTERNALLY_MANAGED=$("$PYBIN" - << 'PY'
import sysconfig, pathlib

# Kandidaten, wo Distros typischerweise ihren EXTERNALLY-MANAGED-Marker platzieren
keys = ("stdlib", "platstdlib", "purelib", "platlib")
paths = []

for key in keys:
    try:
        p = sysconfig.get_path(key)
    except (KeyError, TypeError):
        p = None
    if p:
        paths.append(p)

found = ""

for p in paths:
    base = pathlib.Path(p).resolve()
    # Wir laufen vom jeweiligen Pfad nach oben durch alle Elternverzeichnisse
    for parent in (base, *base.parents):
        marker = parent / "EXTERNALLY-MANAGED"
        if marker.exists():
            # Sobald wir so eine Datei finden, merken wir uns ihren Pfad
            found = str(marker)
            break
    if found:
        break

if found:
    print(found)
PY
)

# -------------------------------------------------------------------
# Hilfsfunktion: PATH um die venv/bin erweitern
# -------------------------------------------------------------------
# add_chatti_path_to_shell_rc <venv_dir>
# - venv_dir  = Wurzelverzeichnis der für Chatti angelegten venv
# - bin_dir   = $venv_dir/bin (dort liegen `python`, `pip`, `chatti` usw.)
add_chatti_path_to_shell_rc() {
  local venv_dir="$1"
  local bin_dir="$venv_dir/bin"

  # Diese Zeile wird später in ~/.bashrc oder ~/.zshrc geschrieben
  # und wirkt bei zukünftigen Shell-Starts:
  #   PATH = <venv>/bin : alter PATH
  local path_line="export PATH=\"$bin_dir:\$PATH\""

  local updated=0

  # Wir bearbeiten nur vorhandene RC-Dateien:
  #  - ~/.bashrc
  #  - ~/.zshrc
  for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    [ -f "$rc" ] || continue
    # Wenn noch kein 'chatti-venv/bin' drin steht, fügen wir unseren Block an
    if ! grep -Fq 'chatti-venv/bin' "$rc"; then
      {
        echo ''
        echo '# Chatti: CLI im PATH verfügbar machen'
        echo "$path_line"
      } >> "$rc"
      echo "   → PATH-Erweiterung in $rc eingetragen: $rc"
      updated=1
    fi
  done

  if [ "$updated" -eq 0 ]; then
    echo "   ℹ️  Keine passende Shell-RC gefunden oder Eintrag bereits vorhanden."
    echo "      Falls nötig, füge manuell hinzu:"
    echo "        $path_line"
  else
    echo "   ✅ Beim nächsten Terminal-Start reicht einfach: chatti"
  fi
}

# -------------------------------------------------------------------
# Hilfsfunktion: Kleine Startdatei ~/bin/chatti anlegen
# -------------------------------------------------------------------
# create_chatti_wrapper <venv_dir>
# - venv_dir  = Wurzelpfad der Chatti-venv (z.B. /home/user/.local/share/chatti-venv)
# - home_bin  = ~/bin (übliches Verzeichnis für Benutzer-Programme)
# - wrapper   = ~/bin/chatti (Mini-Skript, das direkt das venv-chatti startet)
create_chatti_wrapper() {
  local venv_dir="$1"
  local home_bin="$HOME/bin"
  local wrapper="$home_bin/chatti"

  # 1) Sicherstellen, dass ~/bin existiert
  mkdir -p "$home_bin"

  # 2) Kleine Startdatei schreiben, die immer direkt das chatti aus der venv startet
  cat > "$wrapper" << EOF
#!/usr/bin/env bash
exec "$venv_dir/bin/chatti" "\$@"
EOF

  chmod +x "$wrapper"
  echo "   → Startdatei für Chatti angelegt: $wrapper"

  # 3) Prüfen, ob ~/bin bereits im PATH ist
  case ":$PATH:" in
    *":$home_bin:"*)
      echo "   ✅ '$home_bin' ist bereits in deinem PATH."
      echo "      Du kannst ab jetzt einfach: chatti"
      echo "      im Terminal eingeben."
      ;;
    *)
      echo "   ℹ️  '$home_bin' ist noch nicht im PATH."
      echo "      Ich trage es jetzt in deine Shell-Startdateien ein (falls vorhanden)."

      local updated=0
      # Versuche, in die üblichen rc-Dateien einzutragen
      for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
        [ -f "$rc" ] || continue
        if ! grep -Fq 'Chatti: ~/bin in PATH eintragen' "$rc" && \
           ! grep -Fq 'export PATH="$HOME/bin:$PATH"' "$rc"; then
          {
            echo ''
            echo '# Chatti: ~/bin in PATH eintragen'
            echo 'export PATH="$HOME/bin:$PATH"'
          } >> "$rc"
          echo "   → PATH-Erweiterung in $rc eingetragen."
          updated=1
        fi
      done

      if [ "$updated" -eq 0 ]; then
        echo "   ⚠️  Konnte keine passende Shell-Startdatei automatisch anpassen."
        echo "      Falls nötig, füge manuell hinzu (z. B. in ~/.bashrc):"
        echo '        export PATH="$HOME/bin:$PATH"'
      else
        echo "   ✅ Beim nächsten Terminal-Start reicht einfach: chatti"
      fi
      ;;
  esac
}

# -------------------------------------------------------------------
# 5b) Fall: System-Python ist extern verwaltet (PEP 668)
# -------------------------------------------------------------------
# Wenn EXTERNALLY_MANAGED nicht leer ist, haben wir einen Marker gefunden.
# Bedeutet: Die systemweite Python-Umgebung wird nicht angetastet, bitte kein pip install direkt ins System mehr!
# Stattdessen bekommt Chatti seinen eigenen virtuellen Käfig in ~/.local/share/chatti-venv 😊
if [[ -n "${EXTERNALLY_MANAGED}" ]]; then
  echo "⚠️  Dein System-Python ist extern verwaltet:"
  echo "   ${EXTERNALLY_MANAGED}"
  echo "   Debian/Ubuntu blockieren direkte pip-Installationen im System."
  echo
  echo "↪ Ich lege jetzt eine eigene virtuelle Umgebung nur für Chatti an:"

  # VENV_DIR = Ort für die Chatti-eigene venv, unabhängig vom System-Python:
  #   ~/.local/share/chatti-venv
  VENV_DIR="$HOME/.local/share/chatti-venv"
  mkdir -p "$(dirname "$VENV_DIR")"

  # Falls die venv noch nicht existiert -> neu anlegen
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "   → Erzeuge venv unter: $VENV_DIR"
    "$PYBIN" -m venv "$VENV_DIR"
  else
    echo "   → Verwende vorhandene venv unter: $VENV_DIR"
  fi

  # In dieser venv pip aktualisieren (nicht im System!)
  echo "   → Installiere/aktualisiere pip in dieser venv …"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip

  # Wheel mit dem venv-eigenen Python installieren
  echo "   → Installiere Chatti in dieser venv …"
  "$VENV_DIR/bin/python" -m pip install "$WHEEL"

  echo
  echo "✅ Installation abgeschlossen!"
  echo "   Du kannst Chatti jetzt so starten:"
  echo "     $VENV_DIR/bin/chatti"
  echo
  echo "   Um eine kurze Befehlsliste anzuzeigen:"
  echo "     $VENV_DIR/bin/chatti --help"
  echo

  # -------------------------------------------
  # Optional: PATH automatisch erweitern
  # -------------------------------------------
  echo -n "   PATH automatisch erweitern, so dass einfach 'chatti' reicht? [y/N] "
  read -r REPLY_PATH
  case "$REPLY_PATH" in
    [yYjJ]*)
      add_chatti_path_to_shell_rc "$VENV_DIR"
      ;;
    *)
      echo "   → Okay, keine PATH-Änderung."
      ;;
  esac

  echo
  # -------------------------------------------
  # Optional: Startdatei ~/bin/chatti anlegen
  # -------------------------------------------
  echo -n "   Zusätzlich eine kleine Startdatei ~/bin/chatti anlegen, damit du einfach 'chatti' eintippen kannst? [y/N] "
  read -r REPLY_WRAP
  case "$REPLY_WRAP" in
    [yYjJ]*)
      create_chatti_wrapper "$VENV_DIR"
      ;;
    *)
      echo "   → Keine Startdatei angelegt."
      ;;
  esac

  exit 0
fi

# -------------------------------------------------------------------
# 6) Kein extern verwaltetes System -> normale User-Installation
# -------------------------------------------------------------------
# Wenn:
#  - keine aktive venv erkannt wurde (siehe oben)
#  - kein EXTERNALLY-MANAGED-Marker existiert
# dann installieren wir ganz klassisch mit `--user` in ~/.local
echo "↪ Keine venv erkannt – installiere nur für diesen Benutzer (~/.local) …"
"$PYBIN" -m pip install --user "$WHEEL"

echo
echo "✅ Fertig! Starte Chatti jetzt (je nach PATH) mit:"
echo "   chatti --help"