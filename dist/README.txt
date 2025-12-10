Chatti – Installationspaket (Linux / macOS)
==========================================

Dieses Archiv enthält:

  1) chatti_client-0.9.1-py3-none-any.whl (vorkompiliertes Paket, mit sämtlichen Abhängigkeiten)
  2) install-chatti.sh      (Script, das die Installation  automatisiert)
  3) uninstall-chatti.sh    (Entfernt Chatti, nutzt die Pfade, die von install-chatti.sh angelegt wurden)
  4) Diese README.txt

Voraussetzung für eine erfolgreiche Installation:
- Python 3.12 oder neuer muss auf dem Zielsystem installiert sein.
  Bei älteren Versionen bricht die Installation mit einer Hinweismeldung ab.

Installation
------------

1. Archiv entpacken.
2. Im entpackten Ordner ein Terminal öffnen.
3. Installations-Skript ausführbar machen (nur beim ersten Mal nötig):

   chmod +x install-chatti.sh

4. Installation starten:

   ./install-chatti.sh

Das Skript:

- Prüft die Python-Version
- Legt bei Bedarf eine eigene Umgebung für Chatti an
- Installiert Chatti dort hinein
- Fragt dich, ob du Chatti bequem als Befehl "chatti" nutzen möchtest
    👉🏽 Weitere Details im Kommentarblock von install-chatti.sh

Start
-----

Nach der Installation kannst du Chatti im Terminal starten mit:

   chatti
oder
   chatti --help

Deinstallation
--------------

1. Im Ordner mit diesem Archiv ein Terminal öffnen.
2. Das Deinstallations-Skript ausführbar machen (falls nötig):

   chmod +x uninstall-chatti.sh

3. Deinstallation starten:

   ./uninstall-chatti.sh

Hinweis:
- Persönliche Chatti-Daten (Konfiguration, Chat-Verläufe, Anhänge)
  werden NICHT automatisch gelöscht.
- Wenn du wirklich alles entfernen willst, kannst du die Ordner

    ~/.config/chatti-cli
    ~/.local/share/chatti-cli

  manuell löschen (z.B. im Dateimanager).
  
  👉🏽 ~/ steht für User-Home-Verzeichnis