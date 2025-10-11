# Installation Guide for Chatti

Chatti läuft auf allen drei großen Plattformen — **Linux**, **macOS** und **Windows**.
Dieses Dokument beschreibt die empfohlene Vorgehensweise für jede Umgebung.

---

## 🐧 Linux (Debian, Ubuntu, Trixie)

> Chatti benötigt **Python 3.12 oder höher**.
> Unter Linux ist das Modul `venv` oft nicht automatisch installiert – du musst es nachrüsten.

```bash
# 1. System-Pakete aktualisieren
sudo apt update

# 2. Python, venv und pip installieren (Beispiel für Debian 12 / 13)
sudo apt install -y python3.13 python3.13-venv python3-pip python3-setuptools python3-wheel
```
👉🏽  **Hinweis:**
Ein Befehl wie...
sudo apt install python3-pip
...kann, je nach System, dazu führen, dass fehlende abhängige Python-Pakete nachinstalliert werden.
Der Paketmanager apt (aptitude) listet in solchen Fällen alle Abhängigkeiten auf und führt durch die Installation (Details weiter unten).

```bash
# 3. Projekt clonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 4. Virtuelle Umgebung anlegen
```
👉🏽  **Hinweis:**
Dieser Punkt #4 Setzt voraus, dass Punkt #2 abgeschlossen ist.
Danach in den Projektordner ~/chatti (Pfad ggf. anpassen!) wechseln. Dann:
```bash
python3 -m venv .venv
source .venv/bin/activate

# 5. Abhängigkeiten in .venv installieren
pip install -U pip
pip install -r requirements.txt

# 6. Startscript ausführbar machen:
chmod +x ./chatti
```

> 💡 Jetzt kannst du Chatti direkt starten:
> ```bash
> ./chatti_go.py
> ```
> oder mit:
> ```bash
> python -m chatti_go
> ```

---

### ⚠️ Hinweis zu Debian 13 „Trixie“

Bei frisch installierten Systemen kann
```bash
sudo apt install python3-pip
```
eine **umfangreiche Liste zusätzlicher Abhängigkeiten** nach sich ziehen.
Das liegt daran, dass Debian 13 viele Python-Module modularisiert hat – jede Bibliothek steckt nun in einem eigenen Paket.

👉 **Empfohlene Vorgehensweise:**

1. Stelle sicher, dass die „universe“ / „contrib“ Repos aktiviert sind
   (in `/etc/apt/sources.list` oder `/etc/apt/sources.list.d/*.list`).
2. Installiere alle relevanten Pakete in einem Rutsch:
   ```bash
   sudo apt update
   sudo apt install -y \
       python3.13 \
       python3.13-venv \
       python3-pip \
       python3-setuptools \
       python3-wheel
   ```
3. Wenn trotzdem Pakete fehlen, hilft oft:
   ```bash
   sudo apt --fix-broken install
   ```
   oder optional:
   ```bash
   sudo apt install python3-all python3-all-dev
   ```

> 💡 Alternativ kann `pip` auch direkt über Python installiert werden:
> ```bash
> python3 -m ensurepip --upgrade
> ```

---

## 🍎 Installation unter macOS

> **Kurzfassung:**
> macOS bringt eine Python-Version mit, die meist **zu alt** ist.
> Für **Chatti** brauchst du mindestens **Python 3.12**, am besten aus **Homebrew**.

```bash
# 1. Homebrew installieren (falls noch nicht vorhanden)
 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Command Line Tools (Compiler, Header, etc.) installieren
xcode-select --install

# 3. Python 3.12 (oder neuer) via Homebrew installieren
brew install python@3.12

# 4. Projekt klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 5. Virtuelle Umgebung anlegen
python3.12 -m venv .venv
source .venv/bin/activate

# 6. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt
```

💡 **Hinweis:**
- Der Pfad zu Python kann unter macOS variieren (`/opt/homebrew/bin/python3.12` bei Apple Silicon, `/usr/local/bin/python3.12` bei Intel).
- Falls das `activate`-Script nicht gefunden wird: prüfe mit `ls .venv/bin`.

---

## 🪟 Installation unter Windows 10/11

> **Kurzfassung:**
> Verwende die offizielle Python-Distribution von [python.org](https://www.python.org/downloads/).

### Schritt-für-Schritt:

1. Lade den Installer herunter (z. B. *Python 3.12.x Windows Installer*).
2. **Wichtig:** Beim Setup „Add Python to PATH“ aktivieren!
3. Nach der Installation im Terminal (PowerShell oder `cmd`) prüfen:
   ```powershell
   python --version
   pip --version
   ```
4. Repository klonen:
   ```powershell
   git clone git@github.com:enchiriadiae/chatti.git
   cd chatti
   ```
5. Virtuelle Umgebung anlegen:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   ```
6. Abhängigkeiten installieren:
   ```powershell
   pip install -U pip
   pip install -r requirements.txt
   ```

💡 **Hinweise für Windows:**
- Wenn `git` fehlt, kann [Git for Windows](https://git-scm.com/download/win) installiert werden.
- Für VS Code-User: Python-Extension aktivieren, damit die `.venv` automatisch erkannt wird.
- Falls „Execution Policy“ blockiert:
  ```powershell
  Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```
