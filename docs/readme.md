# 💬 Chatti — Dein smarter Terminal-Client für ChatGPT

**Chatti** ist ein leichtgewichtiger, textbasierter Client für die OpenAI-API.
Er läuft vollständig im Terminal (TUI) und bringt eine klare, robuste Architektur mit:
- 🔄 Live-Streaming von Antworten
- 📦 Session-Management & History
- 🧩 Attachments, Token-Zähler, Model-Switch
- 🧠 Lokale Sicherheit (Fernet-Crypto, keine Cloud-Abhängigkeit, keine Klartextdaten auf dem Datenträger)
- 🧑‍💻 Entwickelt in Python 3, vollständig Open-Source

---

## 🚀 Schnellstart - Installation aus git
👉🏽**Hinweis:**
Eine ausführlichere Installationsanleitung liegt im (Projekt)-Order:
/chatti/docs/installation-guide.md

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
python3.13 -m venv .venv
source .venv/bin/activate

# 5. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt
```

### 3️⃣ 💡 Danach kannst du Chatti direkt starten:
```bash
./chatti_go.py
```
Alternativ mit:
```bash
python -m chatti_go
```


### 4️⃣ Testlauf
```bash
./scripts/release_smoke.sh
```

Wenn alles grün ist → 🎉 **Chatti** läuft!


## 🧭 Nächste Schritte:
📘 Getting Started →
Detaillierte Anleitung zur lokalen Entwicklungsumgebung
(inkl. virtueller Python-Umgebung und Setup-Hinweisen).

📗 MANUAL →
Komplette Referenz mit allen Kommandos (:doctor, :attach-*, :whoami, …).


## Für Entwickler:
🛠️ Entwicklungsrichtlinien
•	Bitte keine Secrets (API-Keys, chatti.conf) committen!
•	Alle persönlichen Daten liegen außerhalb des Projektordners.


🧑‍💻 Autoren & Mitwirkende
Thomas Jung (enchiriadiae) — Konzept, Design, Code
ChatGPT (GPT-5) — Dokumentation, Code-Assistenz, Architektur-Review
