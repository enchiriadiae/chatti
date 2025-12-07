
# Installation Guide for Chatti

Chatti läuft auf allen drei großen Plattformen — **Linux**, **macOS** und **Windows**.  
Dieses Dokument beschreibt die empfohlene Vorgehensweise für jede Umgebung und zeigt dir drei Wege, Chatti zu installieren:

- **Weg A:** Direkt aus dem Git-Projekt mit virtueller Umgebung (Entwickler-Modus)
- **Weg B:** Installation aus dem fertigen Wheel-Paket (`.whl`)
- **Weg C:** Installation aus dem Quellpaket (`.tar.gz`)

Such dir dein Betriebssystem aus, scrolle zu dem Abschnitt und folge den Schritten.

---

## 🐧 Linux (Debian, Ubuntu, Trixie)

> Chatti benötigt **Python 3.12 oder höher**.  
> Unter Linux ist das Modul `venv` oft nicht automatisch installiert – du musst es ggf. nachrüsten.

Wenn deine Python-Version zu alt ist (z.B. 3.8 oder 3.9), bricht pip die Installation von chatti-client mit einer Meldung wie
requires a different Python: X.Y not in '>=3.12'
ab. In dem Fall bitte zuerst Python aktualisieren.

```bash
# 1. System-Pakete aktualisieren
sudo apt update

# 2. Python, venv und pip installieren (Beispiel für Debian 12 / 13)
sudo apt install -y python3.13 python3.13-venv python3-pip python3-setuptools python3-wheel
```

👉🏽  **Hinweis:**  
Ein Befehl wie
```bash
sudo apt install python3-pip
```
kann, je nach System, dazu führen, dass fehlende abhängige Python-Pakete nachinstalliert werden.  
Der Paketmanager `apt` listet in solchen Fällen alle Abhängigkeiten auf und führt durch die Installation (Details weiter unten).

---

### 🅰️ Weg A – Chatti direkt aus dem Git-Projekt starten (Entwickler-Modus)

Dieser Weg ist ideal, wenn du selbst am Code arbeiten möchtest.

```bash
# 3. Projekt klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 4. Virtuelle Umgebung anlegen
python3 -m venv .venv
source .venv/bin/activate

# 5. Abhängigkeiten in .venv installieren
pip install -U pip
pip install -r requirements.txt
```

Jetzt kannst du Chatti direkt aus dem Projektordner starten, zum Beispiel mit:

```bash
python -m scripts.chatti_go
```

(Alternativ kannst du dir ein kleines Startskript wie `./chatti_start` anlegen, das genau diesen Befehl ausführt.)

---

### 🅱️ Weg B – Installation aus dem Wheel-Paket (`.whl`)

Dieser Weg installiert Chatti wie ein normales Tool für deinen Benutzer.  
Du brauchst die Datei:

- `dist/chatti_client-0.9.1-py3-none-any.whl`

Das Wheel kannst du dir z. B. aus dem Git-Projekt heraus mit `python -m build` erzeugen.

```bash
# 1. In das Verzeichnis mit dem Wheel wechseln
cd /pfad/zu/deinem/chatti-projekt

# 2. Wheel installieren (ohne venv, nur für aktuellen Benutzer)
python3 -m pip install --user dist/chatti_client-0.9.1-py3-none-any.whl

# 3. Chatti starten
chatti
```

Wenn `chatti` nicht gefunden wird, fehlt vermutlich `~/.local/bin` in deinem `PATH`.  
Füge es in `~/.bashrc` oder `~/.zshrc` hinzu:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

### 🅾️ Weg C – Installation aus dem Quellpaket (`.tar.gz`)

Statt des Wheel kannst du auch das Quellpaket verwenden:

- `dist/chatti_client-0.9.1.tar.gz`

```bash
# 1. In das Verzeichnis mit dem Archiv wechseln
cd /pfad/zu/deinem/chatti-projekt

# 2. Paket installieren
python3 -m pip install --user dist/chatti_client-0.9.1.tar.gz

# 3. Chatti starten
chatti
```

Das Verhalten ist dasselbe wie bei Weg B – nur die Paketquelle unterscheidet sich.

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
```

Der Pfad zu Python kann z. B. so aussehen:

- Apple Silicon (M1/M2/M3): `/opt/homebrew/bin/python3.12`
- Intel-Macs: `/usr/local/bin/python3.12`

---

### 🅰️ Weg A – Chatti aus dem Git-Projekt (mit venv)

```bash
# 4. Projekt klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 5. Virtuelle Umgebung anlegen
python3 -m venv .venv
source .venv/bin/activate

# 6. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt
```

Starten:

```bash
python -m scripts.chatti_go
```

---

### 🅱️ Weg B – Installation aus dem Wheel (`.whl`)

Voraussetzung: Du hast das Wheel `dist/chatti_client-0.9.1-py3-none-any.whl` (z. B. aus dem Git-Projekt gebaut).

```bash
# 1. In das Verzeichnis mit dem Wheel wechseln
cd /pfad/zu/deinem/chatti-projekt

# 2. Paket für den aktuellen Benutzer installieren
python3 -m pip install --user dist/chatti_client-0.9.1-py3-none-any.whl

# 3. Chatti starten
chatti
```

Falls `chatti` nicht gefunden wird, stelle sicher, dass `~/Library/Python/3.12/bin`  
oder `~/.local/bin` (je nach Setup) in deinem `PATH` liegt.

---

### 🅾️ Weg C – Installation aus dem Quellpaket (`.tar.gz`)

```bash
# 1. In das Verzeichnis mit dem Archiv wechseln
cd /pfad/zu/deinem/chatti-projekt

# 2. Paket installieren
python3 -m pip install --user dist/chatti_client-0.9.1.tar.gz

# 3. Chatti starten
chatti
```

---

## 🪟 Installation unter Windows 10/11

> **Kurzfassung:**  
> Verwende die offizielle Python-Distribution von [python.org](https://www.python.org/downloads/).  
> Chatti benötigt mindestens **Python 3.12**.

### 1️⃣ Python einrichten

1. Installer von python.org herunterladen (z. B. *Python 3.12.x Windows Installer*).
2. Beim Setup unbedingt **„Add Python to PATH“** aktivieren.
3. Nach der Installation in PowerShell prüfen:
   ```powershell
   python --version
   pip --version
   ```

---

### 🅰️ Weg A – Chatti aus dem Git-Projekt (mit venv)

```powershell
# 2. Repository klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 3. Virtuelle Umgebung anlegen
python -m venv .venv
.\.venv\Scriptsctivate

# 4. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt

# 5. Chatti starten
python -m scripts.chatti_go
```

---

### 🅱️ Weg B – Installation aus dem Wheel (`.whl`)

Voraussetzung: Du hast die Datei `dist\chatti_client-0.9.1-py3-none-any.whl`.

```powershell
# 1. In das Verzeichnis mit dem Wheel wechseln
cd C:\Pfad\zu\deinem\chatti-projekt

# 2. Paket installieren
python -m pip install dist\chatti_client-0.9.1-py3-none-any.whl

# 3. Chatti starten
chatti
```

Wenn `chatti` nicht gefunden wird, schließe die PowerShell und öffne ein neues Fenster  
(damit der PATH neu eingelesen wird). Notfalls prüfen mit:

```powershell
where chatti
```

---

### 🅾️ Weg C – Installation aus dem Quellpaket (`.tar.gz`)

```powershell
# 1. In das Verzeichnis mit dem Archiv wechseln
cd C:\Pfad\zu\deinem\chatti-projekt

# 2. Paket installieren
python -m pip install dist\chatti_client-0.9.1.tar.gz

# 3. Chatti starten
chatti
```

---

## 🔧 Typische Probleme & Tipps

- **`chatti: command not found` (Linux/macOS)**  
  → Prüfen, ob `~/.local/bin` (oder der entsprechende Benutzer-Bin-Pfad) im `PATH` ist.

- **`python` startet alte Version (z. B. 3.9)**  
  → Prüfen mit `python --version` und ggf. `python3` verwenden oder den Pfad explizit setzen.

- **Pakete fehlen trotz Installation**  
  → Bei Mischinstallationen aus System-Python + Benutzer-Python hilft es oft, konsequent  
    `python3 -m pip ...` (Linux/macOS) bzw. `python -m pip ...` (Windows) zu verwenden.

Sobald Chatti installiert ist (egal mit welchem Weg), läuft die Bedienung überall gleich:  
Du startest mit `chatti` (oder im Dev-Modus mit `python -m scripts.chatti_go`) und arbeitest im TUI-Client weiter.
