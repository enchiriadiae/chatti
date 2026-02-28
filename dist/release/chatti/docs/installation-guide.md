# Installation Guide for Chatti

Chatti läuft auf allen drei großen Plattformen — **Linux**, **macOS** und **Windows**.  
Dieses Dokument beschreibt die empfohlene Vorgehensweise für jede Umgebung und zeigt dir mehrere Wege, Chatti zu installieren:

- **Weg A (empfohlen für Linux/macOS, experimentell für Windows):** Installation per Installations-Skript + Wheel  
  - Linux/macOS: `install-chatti.sh`  
  - Windows: `install-chatti.ps1` (experimentell – bitte mit etwas Vorsicht testen)
- **Weg B:** Direkt aus dem Git-Projekt mit virtueller Umgebung (Entwickler-Modus)
- **Weg C:** Installation aus dem fertigen Wheel-Paket (`.whl`)
- **Weg D:** Installation aus dem Quellpaket (`.tar.gz`)

Such dir dein Betriebssystem aus, scrolle zu dem Abschnitt und folge den Schritten wie in einem Kochrezept. 🙂

---

## 🐧 Linux (Debian, Ubuntu, Trixie)

> Chatti benötigt **Python 3.12 oder höher**.  
> Unter Linux ist das Modul `venv` oft nicht automatisch installiert – du musst es ggf. nachrüsten.

Wenn deine Python-Version zu alt ist (z. B. 3.8 oder 3.9), bricht `pip` die Installation von `chatti-client` mit einer Meldung wie  
`requires a different Python: X.Y not in '>=3.12'`  
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

### 🅰️ Weg A (empfohlen) – Installation mit `install-chatti.sh` + Wheel (Linux/macOS)

Dieser Weg ist für die meisten Nutzer am einfachsten.  
Du brauchst nur **zwei Dateien** in einem Verzeichnis:

- `chatti_client-0.9.1-py3-none-any.whl`
- `install-chatti.sh`  
  (optional zusätzlich: `uninstall-chatti.sh` und eine kleine `README.txt`)

**Schritte:**

```bash
# 1. In das Verzeichnis wechseln, in dem .whl und install-chatti.sh liegen
cd /pfad/zu/deinem/chatti-archiv

# 2. Skript ausführbar machen
chmod +x install-chatti.sh

# 3. Installation starten
./install-chatti.sh
```

Das Skript erledigt dann:

- prüft, ob eine passende Python-Version vorhanden ist (>= 3.12),
- erkennt, ob dein System-Python „extern verwaltet“ ist (PEP 668),
- legt bei Bedarf automatisch eine **eigene virtuelle Umgebung** an:  
  `~/.local/share/chatti-venv`
- installiert das Wheel `chatti_client-0.9.1-py3-none-any.whl` in dieser venv,
- fragt dich auf Wunsch:
  - ob `chatti-venv/bin` automatisch in deinen `PATH` eingetragen werden soll,
  - ob eine kleine Startdatei `~/bin/chatti` angelegt werden soll.

**Chatti starten:**

- Wenn das Skript PATH und Startdatei eingerichtet hat:

  ```bash
  chatti
  ```

- Ohne Extras:

  ```bash
  ~/.local/share/chatti-venv/bin/chatti
  ```

**Deinstallation (optional):**

Wenn du zusätzlich `uninstall-chatti.sh` im Verzeichnis hast:

```bash
chmod +x uninstall-chatti.sh
./uninstall-chatti.sh
```

Das Skript entfernt dabei:

- die venv `~/.local/share/chatti-venv`,
- die Startdatei `~/bin/chatti` (falls vorhanden),
- optional den PATH-Eintrag für `chatti-venv/bin`.

Deine eigentlichen **Chatti-Daten** (Konfiguration, History, Anhänge) bleiben erhalten:

- `~/.config/chatti-cli/…`
- `~/.local/share/chatti-cli/…`

So kannst du Chatti später neu installieren, ohne alles zu verlieren.

---

### 🅱️ Weg B – Chatti direkt aus dem Git-Projekt (Entwickler-Modus, Linux/macOS)

Dieser Weg ist ideal, wenn du selbst am Code arbeiten möchtest.

```bash
# 1. Projekt klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 2. Virtuelle Umgebung anlegen
python3 -m venv .venv
source .venv/bin/activate

# 3. Abhängigkeiten in .venv installieren
pip install -U pip
pip install -r requirements.txt
```

Jetzt kannst du Chatti direkt aus dem Projektordner starten, z. B. mit:

```bash
python -m scripts.chatti_go
```

(Alternativ kannst du dir ein kleines Startskript wie `./chatti-start.sh` anlegen, das genau diesen Befehl ausführt.)

---

### 🅾️ Weg C – Installation aus dem Wheel-Paket (`.whl`, Linux/macOS)

Dieser Weg installiert Chatti wie ein normales Tool für deinen Benutzer.  
Du brauchst die Datei:

- `dist/chatti_client-0.9.1-py3-none-any.whl`

Das Wheel kannst du dir z. B. aus dem Git-Projekt heraus mit `python -m build` erzeugen.

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

### 🅳 Weg D – Installation aus dem Quellpaket (`.tar.gz`, Linux/macOS)

Statt des Wheels kannst du auch das Quellpaket verwenden:

- `dist/chatti_client-0.9.1.tar.gz`

```bash
# 1. In das Verzeichnis mit dem Archiv wechseln
cd /pfad/zu/deinem/chatti-projekt

# 2. Paket installieren
python3 -m pip install --user dist/chatti_client-0.9.1.tar.gz

# 3. Chatti starten
chatti
```

Das Verhalten ist dasselbe wie bei Weg C – nur die Paketquelle unterscheidet sich.

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

Der Pfad zu Python kann z. B. so aussehen:

- Apple Silicon (M1/M2/M3): `/opt/homebrew/bin/python3.12`
- Intel-Macs: `/usr/local/bin/python3.12`

---

### 🅰️ Weg A (empfohlen) – Installation mit `install-chatti.sh` + Wheel (macOS)

Die Vorgehensweise ist identisch wie unter Linux:

1. Lege in einem Ordner ab:

   - `chatti_client-0.9.1-py3-none-any.whl`  
   - `install-chatti.sh`

2. Terminal öffnen, in diesen Ordner wechseln:

   ```bash
   cd /Pfad/zu/deinem/chatti-archiv
   chmod +x install-chatti.sh
   ./install-chatti.sh
   ```

Das Skript erkennt die Python-Version, legt bei Bedarf `~/.local/share/chatti-venv` an und installiert Chatti dort hinein.  
Am Ende kannst du – je nach Auswahl – einfach:

```bash
chatti
```

oder explizit:

```bash
~/.local/share/chatti-venv/bin/chatti
```

starten.

---

### 🅱️ Weg B – Chatti aus dem Git-Projekt (mit venv, macOS)

```bash
# 1. Projekt klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 2. Virtuelle Umgebung anlegen
python3 -m venv .venv
source .venv/bin/activate

# 3. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt
```

Starten:

```bash
python -m scripts.chatti_go
```

---

### 🅾️ Weg C – Installation aus dem Wheel (`.whl`, macOS)

Voraussetzung: Du hast das Wheel `dist/chatti_client-0.9.1-py3-none-any.whl` (z. B. aus dem Git-Projekt gebaut).

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

### 🅳 Weg D – Installation aus dem Quellpaket (`.tar.gz`, macOS)

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

1. Installer von python.org herunterladen (z. B. *Python 3.12.x Windows Installer*).
2. Beim Setup unbedingt **„Add Python to PATH“** aktivieren.
3. Nach der Installation in PowerShell prüfen:

   ```powershell
   python --version
   pip --version
   ```

---

### 🅰️ Weg A (experimentell) – Installation mit `install-chatti.ps1` + Wheel (Windows)

> ⚠️ **Experimentell:**  
> Dieses Vorgehen ist aktuell als „Work in Progress“ zu verstehen.  
> Es entspricht konzeptionell dem Linux/macOS-Skript, wurde aber noch nicht auf verschiedenen Windows-Versionen umfangreich getestet.

Du brauchst zwei Dateien in einem Ordner, z. B. `C:\Users\<Name>\Downloads\chatti-setup`:

- `chatti_client-0.9.1-py3-none-any.whl`
- `install-chatti.ps1`

**Einmalig Skriptausführung erlauben (falls nötig):**

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Installation starten:**

```powershell
cd C:\Pfad\zu\deinem\chatti-archiv
.\install-chatti.ps1
```

Das Skript erledigt für dich (analog zum Bash-Script):

- sucht eine passende Python-Version (mindestens 3.12),
- legt eine eigene virtuelle Umgebung im Benutzerbereich an  
  (z. B. `%LOCALAPPDATA%\chatti-venv` oder ähnlich),
- installiert das Wheel `chatti_client-0.9.1-py3-none-any.whl` in diese venv,
- kann auf Wunsch den Pfad so erweitern, dass du einfach `chatti` eintippen kannst.

**Chatti starten (typischerweise):**

```powershell
chatti
```

oder – falls kein PATH-Eintrag gesetzt wurde – explizit über den vollständigen Pfad der venv, z. B.:

```powershell
C:\Users\<Name>\AppData\Local\chatti-venv\Scripts\chatti.exe
```

> 💡 Solange dieses Skript noch experimentell ist, kannst du immer auf die klassischen Wege B–D ausweichen.

---

### 🅱️ Weg B – Chatti aus dem Git-Projekt (mit venv, Windows)

```powershell
# 1. Repository klonen
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

# 2. Virtuelle Umgebung anlegen
python -m venv .venv
.\.venv\Scripts\activate

# 3. Abhängigkeiten installieren
pip install -U pip
pip install -r requirements.txt

# 4. Chatti starten
python -m scripts.chatti_go
```

---

### 🅾️ Weg C – Installation aus dem Wheel (`.whl`, Windows)

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

### 🅳 Weg D – Installation aus dem Quellpaket (`.tar.gz`, Windows)

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

- **`chatti` wird unter Windows nicht gefunden**  
  → Neues PowerShell-Fenster öffnen und mit `where chatti` prüfen, wo die Datei liegt.  
    Ggf. den Pfad zu `Scripts\` der venv manuell in die PATH-Umgebungsvariable aufnehmen.

- **`python` startet alte Version (z. B. 3.9)**  
  → Prüfen mit `python --version` und ggf. den korrekten Python-Pfad verwenden oder die 3.12-Installation nachziehen.

- **Pakete fehlen trotz Installation**  
  → Bei Mischinstallationen aus System-Python + Benutzer-Python hilft es oft, konsequent  
    `python3 -m pip ...` (Linux/macOS) bzw. `python -m pip ...` (Windows) zu verwenden.

Sobald Chatti installiert ist (egal mit welchem Weg), läuft die Bedienung überall gleich:  
Du startest mit `chatti` (oder im Dev-Modus mit `python -m scripts.chatti_go`) und arbeitest im TUI-Client weiter.
