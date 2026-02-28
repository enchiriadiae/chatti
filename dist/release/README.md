# 💬 Chatti — Dein smarter Terminal-Client für ChatGPT
Stand: früher Dezember 2025

**Chatti** ist ein leichtgewichtiger, textbasierter Client für die OpenAI-API.
Er läuft vollständig im Terminal (TUI) und bringt eine klare, robuste Architektur mit:
- 🔄 Live-Streaming von Antworten
- 📦 Session-Management & History
- 🧩 Attachments, Token-Zähler, Model-Switch
- 🧠 Lokale Sicherheit (Fernet-Crypto, keine Cloud-Abhängigkeit, keine Klartextdaten auf dem Datenträger)
- 🧑‍💻 Entwickelt in Python 3, vollständig Open-Source



## 🚀 Schnellstart - Installation aus git
👉🏽**Hinweis:**
Eine ausführlichere Installationsanleitung liegt im (Projekt)-Order:
/chatti/docs/installation-guide.md

Homepage/Wiki:
https://wiki.tuxi.ddnss.de/wiki/ChatGPT-Client_-_Wiki

👉🏽 Doku und Wiki entstehen zum Zeitpunkt dieser README.md und sind entsprechend unvollständig.

### 1️⃣ Repository klonen
```bash
git clone git@github.com:enchiriadiae/chatti.git
cd chatti
```

### 2️⃣ 🐍 Python & virtuelle Umgebung ([v]irtual [env]ironment) anlegen:
**Chatti** benötigt Python 3.12 oder höher.
Unter Linux ist das Modul venv oft nicht automatisch installiert – in diesem Fall nachrüsten.

```bash
# 1. System-Pakete aktualisieren
sudo apt update
sudo apt upgrade

# 2. Python, venv und pip installieren (Beispiel für Debian 12 / Trixie)
sudo apt install -y python3.13 python3.13-venv python3-pip

# oder unter Windows:
# .\.venv\Scripts\Activate.ps1

# 3. Projekt clonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 4. Virtuelle Umgebung anlegen
python3 -m venv .venv
source .venv/bin/activate

# 5. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt
```

### 3️⃣ 💡 Danach kannst du Chatti in der virtuellen Umgebung direkt starten:

```bash
./chatti
```

Um Chatti wieder zu verlassen, in's Eingabefenster...
```bash
:q
```
...tippen. Danach die Tabulator-Taste und ENTER.
Details zur Bedienung sieh Abschnitt "Kurzbedienung im Client" weiter unten.

### 4️⃣ Testlauf
```bash
./scripts/release_smoke.sh
```
Wenn alles grün ist → 🎉 **Chatti** läuft!


Kurz gesagt:
- `hatchling` baut aus dem Projekt ein „richtiges“ Python-Paket (Wheel/Source-Tarball).
- Damit kann Chatti später mit einem einzigen  
  `pip install .`  
  (oder irgendwann `pip install chatti-client`) installiert werden – inklusive aller Abhängigkeiten.
- Der CLI-Befehl `chatti` wird dabei automatisch ins `$PATH` gelegt (über `[project.scripts]` in `pyproject.toml`).
- `requirements.txt` bleibt vor allem für Entwickler*innen und reproduzierbare Dev-Umgebungen gedacht  
  (z. B. `pip install -r requirements.txt`),  
  während `pyproject.toml` + `hatchling` das saubere Packaging und die Verteilung übernehmen.




### 5️⃣ Die beiden make-Files:


## Release-Skripte

Für wiederholbare Releases gibt es zwei Hilfsskripte im Verzeichnis `scripts/`:

### `scripts/make-release.sh` – Source-Release (Entwickler:innen)

Dieses Skript baut ein **Source-Bundle** des Projekts unter `dist/release/`.

- liest die aktuelle Versionsnummer aus `core/__init__.py` (`__version__ = "…"`)
- führt optional einen kurzen **Import-Smoketest** aus  
  (Import von `core.paths`, `core.api`, `tools.chatti_doctor`, …)
- legt `dist/release/` neu an (ohne den restlichen `dist`-Ordner anzufassen)
- kopiert den kompletten Projektbaum nach `dist/release/`,  
  dabei ausgeschlossen:
  - `.venv`, `.git`, `__pycache__`, `dist`, `*.pyc`, `*.pyo`, `.DS_Store`
- erzeugt falls nötig eine `requirements.txt` (per `pip freeze`)
- schreibt eine `VERSION.txt` und eine minimale `INSTALL.md` ins Release-Verzeichnis

**Aufruf:**

```bash
chmod +x scripts/make-release.sh
scripts/make-release.sh
# oder ohne Import-Smoketest:
scripts/make-release.sh --no-smoke
```


scripts/make-bundle.sh – Enduser-Bundle (Wheel + sdist + ZIP)

Dieses Skript baut ein fertiges Distributions-Bundle für Endanwender:innen:
	•	wechselt automatisch in die Projektwurzel (dort, wo pyproject.toml liegt)
	•	liest die Version aus pyproject.toml (project.version)
	•	räumt dist/ auf und ruft...

```bash
python3 -m build
```

...auf → erzeugt:
	•	dist/chatti_client-<VERSION>-py3-none-any.whl
	•	dist/chatti_client-<VERSION>.tar.gz

	•	packt anschließend in ein ZIP:
	•	das Wheel
	•	das sdist
	•	install-chatti.sh
	•	uninstall-chatti.sh
	•	README.txt (Bundle-Readme)
	•	Ergebnis ist ein handliches Archiv:
dist/chatti_client-<VERSION>-bundle.zip


## Aufruf:
```bash
chmod +x scripts/make-bundle.sh
scripts/make-bundle.sh
```

Dieses ZIP kann 1:1 auf einen Webserver.
Enduser müssen dann nur das Archiv herunterladen, entpacken und install-chatti.sh ausführen.


### 6️⃣ Basics

📂 Konfiguration & Datenpfade (Überblick)
```
~/.config/chatti-cli          # Konfiguration (z. B. chatti.conf, User-Einstellungen)
~/.local/share/chatti-cli     # Laufzeitdaten & pro-User-Daten
└── users/<UID>/...           # History, Support-Tickets, evtl. Attachments etc.
```
<UID> ist eine verschlüsselte User-ID (z. B. 1R_q0s9AevuWIXP0shoqaQ), unter der dein Profil geführt wird.
In users/<UID>/support/ liegt z. B. der einfache „Ticket“-Mechanismus (eine Datei pro Ticket).
Diese Verzeichnisse sind die zentrale Anlaufstelle, wenn du Backups oder Migrationen machen willst.

⌨️ Kurzbedienung im Client

Ein paar Basics, um loszulegen:
Nachricht senden
	•	Enter → Zeilenumbruch im Eingabefeld
	•	TAB+Enter → Nachricht (Command, was auch immer) abschicken.

Kommandos & Hilfe (alles mit TAB+Enter abschicken)
	•	:help → kurze Übersicht
	•	:commands → Liste aller verfügbaren Kommandos
	•	:doctor → Diagnose (Modelle, Reachability, API-Status)
	•	:change-openai-model → anderes Modell wählen und speichern
	•	:show-openai-model → aktuell verwendetes Modell anzeigen
	•	Kommandos schneller tippen
	•	Alt/Option + → (Pfeil rechts) im Eingabefeld
→ auto-completed :att… zu :attach-file usw.

Clipboard (gesamter Chat)
	•	Ctrl+Y → gesamten aktuellen Chatverlauf ins Clipboard kopieren
	•	nutzt zuerst pyperclip (lokales Clipboard)
	•	fällt bei SSH-Terminals auf OSC52 zurück
	•	Hinweis: Das Standard-Terminal von macOS kann OSC52 nicht, mit iTerm2 funktioniert es sehr gut.

Alle Details und weitere Features (Search-Mode, History, Boss-Mode, Attachments, Tickets, …) stehen im MANUAL.

## 🧭 Nächste Schritte:

🔧 Nützliche CLI-Optionen
Chatti lässt sich auch direkt von der Kommandozeile steuern – ohne TUI:

```bash
# Kurzcheck: lebt mein API-Key & Modell?
./chatti --verify
```


📘 Getting Started →
Detaillierte Anleitung zur lokalen Entwicklungsumgebung
(inkl. virtueller Python-Umgebung und Setup-Hinweisen).

📗 MANUAL →
Komplette Referenz mit allen Kommandos (:doctor, :attach-*, :whoami, …).

📖 Manpage:
Ist im Projekt integriert und über das Hilfsskript showman erreichbar.
```bash
./showman.sh
```

## Für Entwickler:
🛠️ Entwicklungsrichtlinien
•	Bitte keine Secrets (API-Keys, chatti.conf) committen!
•	Alle persönlichen Daten liegen außerhalb des Projektordners.


💻 Autoren & Mitwirkende
Thomas Jung (enchiriadiae) — Konzept, Design, Code
ChatGPT (GPT-5) — Dokumentation, Code-Assistenz, Architektur-Review
