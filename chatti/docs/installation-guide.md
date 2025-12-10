# Installation Guide für Chatti

Chatti läuft auf **Linux**, **macOS** und **Windows**.  
Du brauchst überall:

- **Python 3.12 oder höher** (z. B. 3.12 oder 3.13)
- Einen Internetzugang (für die OpenAI-API)
- Einen gültigen **OpenAI API-Key**

> ℹ️ Wenn deine Python-Version zu alt ist (z. B. 3.8 oder 3.9), schlagen die Installationen mit einer Meldung wie  
> `requires a different Python: X.Y not in '>=3.12'` fehl.  
> In dem Fall: erst Python aktualisieren.

---

## Überblick: Installationswege

Es gibt diverse Möglichkeiten, Chatti zu installieren.
Vier Alternativen sind im Folgenden beschrieben. Die erste ist am komfortabelsten.

1. **Weg 1 – Komfort-Bundle (empfohlen für Linux/macOS)**  
   ZIP mit:
   - `chatti_client-0.9.1-py3-none-any.whl`
   - `install-chatti.sh` / `uninstall-chatti.sh`
   - `README.txt`  
   → Entpacken, Script starten, fertig.

2. **Weg 2 – Installation mit `pip` aus `dist/`**  
   Du verwendest das fertige **Wheel** (`.whl`) oder das **Quellpaket** (`.tar.gz`) direkt mit `pip`.

3. **Weg 3 – Eigene Release-Kopie mit `make-release.sh`**  
   Du baust dir ein eigenes „Source-Bundle“ (z. B. für Archiv/Backup).

4. **Weg 4 – Entwicklermodus aus Git (mit `chatti-start.sh`)**  
   Du clonest das Git-Repo, arbeitest im Quellcode und startest Chatti direkt daraus.

> 🔮 **Später einmal** könnte noch ein „Weg 0 – Installation über PyPI“ dazukommen  
> (`pip install chatti-client`). Das wäre dann ganz oben – an der Nummerierung hier müssten wir nichts ändern.

---

## Weg 1 – Komfort-Bundle mit `install-chatti.sh` (empfohlen)

Dieser Weg ist für **Linux** und **macOS** gedacht und zielt auf Leute, die einfach nur:
- Archiv entpacken,
- ein Script starten,
- und danach nur noch `chatti` eintippen wollen.

### 1.1 Vorbereitung

Du bekommst ein ZIP über folgende Quellen:
- im `dist/`-Ordner deines Projekts (Datei: chatti_client-0.9.1-bundle.zip)
Alternativ über die Chattis Homepage:
- https://wp.tuxi.ddnss.de/wp-content/uploads/2025/12/chatti_client-0.9.1-bundle.zip

- `chatti_client-0.9.1-py3-none-any.whl`
- `install-chatti.sh`
- `uninstall-chatti.sh`
- `README.txt`

Entpacke das Archiv in ein Verzeichnis deiner Wahl, z. B.:

```bash
mkdir -p ~/Downloads/chatti-bundle
cd ~/Downloads/chatti-bundle
unzip chatti_client-0.9.1-bundle.zip
```

### 1.2 Voraussetzungen prüfen (Python-Version)

Unter Linux/macOS:

```bash
python3 --version
```

- Wenn die Ausgabe z. B. `Python 3.13.x` ist → ✅ alles gut.
- Wenn da etwas wie `Python 3.9.x` steht → vorher **Python 3.12+ installieren**.

### 1.3 Installation mit `install-chatti.sh` (Linux/macOS)

Im entpackten Bundle-Verzeichnis:

```bash
cd ~/Downloads/chatti-bundle

# 1. Script ausführbar machen
chmod +x install-chatti.sh

# 2. Installation starten
./install-chatti.sh
```

Was das Script macht:

- sucht ein passendes **Python 3.12+**  
- prüft, ob dein System-Python **PEP 668 / EXTERNALLY-MANAGED** markiert ist  
  (z. B. bei neuen Debian/Ubuntu-Versionen)  
- legt eine **eigene virtuelle Umgebung** an:

  ```text
  ~/.local/share/chatti-venv
  ```

- installiert darin:
  - `pip` (aktuell)
  - alle Abhängigkeiten
  - das Wheel `chatti_client-0.9.1-py3-none-any.whl`
- bietet dir an:
  - deinen **PATH automatisch zu erweitern**, sodass `chatti` direkt gefunden wird
  - eine **Startdatei `~/bin/chatti`** anzulegen

Am Ende siehst du z. B.:

```text
✅ Installation abgeschlossen!
   Du kannst Chatti jetzt so starten:
     /home/deinname/.local/share/chatti-venv/bin/chatti

   (Optional: Wenn PATH-Erweiterung/Startdatei aktiv ist, reicht einfach: chatti)
```

### 1.4 Starten von Chatti (nach Weg 1)

- Mit PATH-Erweiterung/Startdatei:  

  ```bash
  chatti
  ```

- Ohne:  

  ```bash
  ~/.local/share/chatti-venv/bin/chatti
  ```

Hilfe:

```bash
chatti --help
chatti --readme
chatti --manual
```

### 1.5 Deinstallation mit `uninstall-chatti.sh`

Später kannst du Chatti sauber entfernen:

```bash
cd ~/Downloads/chatti-bundle
chmod +x uninstall-chatti.sh
./uninstall-chatti.sh
```

Das Script:

- entfernt die venv `~/.local/share/chatti-venv`
- räumt die Startdatei `~/bin/chatti` auf (falls angelegt)
- räumt PATH-Ergänzungen wieder aus `~/.bashrc` / `~/.zshrc`

**Wichtig:**  
Deine **persönlichen Chatti-Daten** (z. B. Konfiguration, Ticket-Historie) bleiben bewusst liegen:

- `~/.config/chatti-cli/`
- `~/.local/share/chatti-cli/`

Wenn du wirklich alles löschen willst, kannst du diese Verzeichnisse manuell entfernen.

---

## Weg 2 – Installation mit `pip` aus `dist/` (Wheel oder Tarball)

Dieser Weg ist etwas „technischer“, aber immer noch gut beherrschbar.  
Du verwendest direkt:

- das **Wheel**: `chatti_client-0.9.1-py3-none-any.whl`
- oder das **Quellpaket**: `chatti_client-0.9.1.tar.gz`

### 2.1 Linux / macOS

Voraussetzung: **Python 3.12+** ist installiert.

Wechsle in dein Projekt (oder dorthin, wo `dist/` liegt):

```bash
cd /pfad/zu/deinem/chatti-projekt
ls dist
# → chatti_client-0.9.1-py3-none-any.whl
#   chatti_client-0.9.1.tar.gz
```

#### Variante 2a – mit Wheel (`.whl`)

```bash
python3 -m pip install --user dist/chatti_client-0.9.1-py3-none-any.whl
```

#### Variante 2b – mit Quellpaket (`.tar.gz`)

```bash
python3 -m pip install --user dist/chatti_client-0.9.1.tar.gz
```

💡 Der Effekt ist der gleiche, nur die Paketquelle unterscheidet sich.

Danach:

```bash
chatti --help
```

Falls `chatti` nicht gefunden wird, fehlt vermutlich `~/.local/bin` im PATH.  
In `~/.bashrc` oder `~/.zshrc` ergänzen:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

#### Hinweis zu Debian 12/13 („Trixie“) & Co.

Neue Debian/Ubuntu-Systeme nutzen PEP 668 und können bei `pip install --user` meckern (EXTERNALLY-MANAGED).  
In dem Fall nimm lieber **Weg 1 (install-chatti.sh)** – das Script baut automatisch eine eigene venv.

### 2.2 Windows (PowerShell)

Voraussetzung:

- **Python 3.12+** von [python.org](https://www.python.org/downloads/)
- Beim Setup: **„Add Python to PATH“** aktiviert

Dann:

```powershell
cd C:\Pfad\zu\deinem\chatti-projekt

# Variante a – Wheel:
python -m pip install dist\chatti_client-0.9.1-py3-none-any.whl

# Variante b – Tarball:
python -m pip install dist\chatti_client-0.9.1.tar.gz
```

Starten:

```powershell
chatti
chatti --help
```

Wenn `chatti` unbekannt ist:

- neues Terminal öffnen (PATH neu einlesen),
- oder prüfen mit:

```powershell
where chatti
```

---

## Weg 3 – Eigenes Release-Bundle mit `make-release.sh` (für Maintainer)

Dieser Weg ist für dich gedacht, wenn du **selbst Releases bauen** willst  
(z. B. um sie zu verschicken oder zu archivieren).

Script: `scripts/make-release.sh`

### 3.1 Nutzung

Im Projekt-Root:

```bash
cd /pfad/zu/deinem/chatti-projekt
chmod +x scripts/make-release.sh
scripts/make-release.sh
```

Das Script:

1. ermittelt die **Projektversion** aus `core/__init__.py` (`__version__ = "…"`)  
2. macht einen kurzen **Import-Smoketest** (kann mit `--no-smoke` übersprungen werden)  
3. baut unter `dist/release/` eine **vollständige Kopie** des Projekts:
   - ohne `.git`, `.venv`, `__pycache__`, etc.  
4. erzeugt:
   - `dist/release/VERSION.txt`
   - `dist/release/INSTALL.md` (kurze Install-Anleitung)
   - bei Bedarf eine aktualisierte `requirements.txt`

Am Ende hast du eine saubere, „geputzte“ Projektkopie.  
Daraus kannst du z. B. wieder ein ZIP machen.

---

## Weg 4 – Entwicklermodus aus Git (mit `chatti-start.sh`)

Dieser Weg ist ideal, wenn du:

- am Code arbeiten willst
- die Struktur von Chatti verstehen möchtest
- Tests, Debugging etc. machen willst

### 4.1 Git-Repo klonen

```bash
git clone git@github.com:enchiriadiae/chatti.git
cd chatti
```

### 4.2 Entwicklerskript `chatti-start.sh`

Im Repo liegt:

- `chatti-start.sh` (im Projekt-Root)

Das Script:

- sucht eine passende Python-Version (3.12+),
- legt bei Bedarf eine **lokale venv** unter `./.venv` an,
- installiert `requirements.txt` in diese venv,
- startet dann Chatti mit:

  ```bash
  python -m scripts.chatti_go
  ```

### 4.3 Nutzung (Linux/macOS)

```bash
cd /pfad/zu/deinem/chatti-clone
chmod +x chatti-start.sh
./chatti-start.sh
```

Optional mit Argumenten:

```bash
./chatti-start.sh --help
./chatti-start.sh --doctor
```

Das Script sorgt dafür, dass:

- Abhängigkeiten (textual, cryptography, openai, …) in der lokalen venv liegen,
- dein System-Python unberührt bleibt.

### 4.4 Windows: Dev-Setup (ohne `chatti-start.sh`)

Unter Windows kannst du analog vorgehen, aber manueller:

```powershell
git clone git@github.com:enchiriadiae/chatti.git
cd chatti

python -m venv .venv
.\.venv\Scriptsctivate

pip install -U pip
pip install -r requirements.txt

python -m scripts.chatti_go --help
```

---

## Ausblick: Weg 0 – PyPI (noch Zukunftsmusik)

Langfristig könnte Chatti auch über **PyPI** verteilt werden:

```bash
pip install chatti-client
chatti
```

Das wäre dann vermutlich der „Weg 0“ / Standardweg.  
Aktuell steht das noch auf der „später mal“-Liste – die obigen Wege 1–4 funktionieren unabhängig davon.

---

## Typische Probleme & Tipps

- **`chatti: command not found` (Linux/macOS)**  
  → Prüfen, ob `~/.local/bin` bzw. der venv-`bin`-Ordner im PATH ist.  
  → Bei Weg 1 kümmert sich `install-chatti.sh` auf Wunsch darum.

- **Python zu alt (`requires Python >= 3.12`)**  
  → Python über Paketmanager (Linux) oder Installer (Windows/macOS) aktualisieren.

- **PEP 668 / EXTERNALLY-MANAGED (Debian/Ubuntu)**  
  → `pip install --user` im System-Python ist blockiert.  
  → Nimm Weg 1 (`install-chatti.sh`), der automatisch eine venv in `~/.local/share/chatti-venv` anlegt.

- **Mehrere Python-Versionen parallel**  
  → Unter Linux/macOS lieber explizit `python3` nutzen.  
  → Unter Windows gilt: `python` aus dem offiziellen Installer verwenden.

Sobald Chatti installiert ist – egal auf welchem Weg –  
startest du ihn in der Regel einfach mit:

```bash
chatti
```

und arbeitest im Text-UI weiter.
