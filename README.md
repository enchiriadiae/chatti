# Chatti – TUI-Client für OpenAI-Modelle

**Chatti** ist ein schlanker, textbasierter Client für OpenAI-Modelle mit Fokus auf
lokale Sicherheit, verschlüsselte API-Key-Speicherung und gute Bedienbarkeit im Terminal.

- Läuft unter **Linux**, **macOS** und **Windows**
- Speichert API-Keys und Benutzerdaten **verschlüsselt** im Benutzerprofil
- Nutzt eine Text-UI auf Basis von **textual**
- Unterstützt mehrere Benutzer-Profile, History, Tickets & Dateianhänge

---

## Voraussetzungen

- **Python 3.12 oder höher** (z. B. 3.12 oder 3.13)
- Einen gültigen **OpenAI API-Key**
- Internetzugang

Wie man einen API-Key anlegt, steht in `chatti/docs/API-Keys.md`
bzw. im Online-Wiki zum Projekt:
https://wiki.tuxi.ddnss.de/wiki/ChatGPT-Client_-_Wiki

---

## Schnellstart (empfohlen für Linux & macOS)

Für die meisten Nutzer:innen ist das **Komfort-Bundle mit Installationsscript** der einfachste Weg:

1. Lade das ZIP-Bundle herunter (enthält u. a.):  
   - `chatti_client-0.9.1-py3-none-any.whl`  
   - `install-chatti.sh` / `uninstall-chatti.sh`  
   - `README.txt`

2. Entpacke das Archiv, z. B.:

   ```bash
   mkdir -p ~/Downloads/chatti-bundle
   cd ~/Downloads/chatti-bundle
   unzip chatti_client-0.9.1-bundle.zip
   ```

3. Stelle sicher, dass **Python 3.12+** vorhanden ist:

   ```bash
   python3 --version
   ```

4. Installation starten:

   ```bash
   chmod +x install-chatti.sh
   ./install-chatti.sh
   ```

   Das Script:

   - legt eine eigene virtuelle Umgebung unter `~/.local/share/chatti-venv` an,
   - installiert dort alle Abhängigkeiten + Chatti,
   - bietet dir an, automatisch einen PATH-Eintrag und eine Startdatei `~/bin/chatti` zu setzen.

5. Chatti starten:

   ```bash
   chatti
   ```

   (Falls du PATH/Startdatei abgelehnt hast, kannst du auch direkt
   `~/.local/share/chatti-venv/bin/chatti` aufrufen.)

---

## Entwicklermodus aus Git (kurz)

Wenn du am Code arbeiten möchtest:

```bash
git clone git@github.com:enchiriadiae/chatti.git
cd chatti
chmod +x chatti-start.sh
./chatti-start.sh
```

Das Script legt bei Bedarf eine lokale `.venv` an, installiert `requirements.txt`
und startet dann `python -m scripts.chatti_go`.

---

## Weitere Installationswege & Details

Alle anderen Varianten (Wheel-/Tarball-Installation mit `pip`, Release-Builds mit
`make-release.sh`, Dev-Setup unter Windows etc.) sind in
`chatti/docs/installation-guide.md` ausführlich beschrieben.

### Chattis Homepage (in work):
https://wp.tuxi.ddnss.de/chatti-ein-client-fuer-chatgpt/

### Online-Wiki (in work):
https://wiki.tuxi.ddnss.de/wiki/ChatGPT-Client_-_Wiki

---

Viel Spaß mit Chatti! 🐍💬
