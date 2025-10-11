# 📘 Chatti Benutzerhandbuch (manuals.md)

Willkommen zum offiziellen Handbuch des **Chatti Clients**.
Dieses Dokument erklärt alle wesentlichen Funktionen, Konzepte und Arbeitsabläufe.

### Hinweis: ###
Das Dokument ist noch in der Entstehungsphase (Mid October 2025), daher noch unvollständig!
---

## (0) ⚙️ Ersteinrichtung & Setup

Willkommen an Bord! 🚀
Bevor Chatti losplaudern kann, braucht er ein bisschen Zuwendung – und ein paar Werkzeuge.

### 🧰 Was du brauchst
- **Python 3.12+** – je aktueller, desto besser
  (unter Linux via `apt install python3.12-venv`, unter macOS mit Homebrew: `brew install python`)
- **Virtuelle Umgebung** – damit dein System sauber bleibt:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
- **OpenAI API-Key** – ohne den bleibt Chatti stumm.
  Wenn du noch keinen hast: Lies [docs/API-Keys.md](API-Keys.md).

Wenn du detaillierte Infos zur Installation benötigst: Lies [docs/installation-guide.md](installation-guide.md).

### 🧑‍💻 Erststart
Starte Chatti mit:
```bash
./chatti
```
Beim ersten Start fragt dich das Programm:
- nach deinem **API-Key**
- nach einem **Master-Passwort** (für lokale Verschlüsselung)
- nach deinem **Anzeigenamen**

Zugunsten der Sicherheit muss dein Passwort ein paar Kriterien erfüllen.
- Mindestlänge: 12 Zeichen
- Es muss Buchstaben, Ziffern, Sonderzeichen enthalten.
- Bitte: **KEINE** Leerzeichen im Passwort!
- Keyboard-Walks, schwache Passwörter

Alles wird **verschlüsselt lokal** gespeichert – nichts verlässt deinen Rechner.
Wenn alles klappt, siehst du ein freundliches ASCII-Art und den Begrüßungstext:


### 🧪 Testlauf („Smoke-Test“)
Führe zur Sicherheit einmal aus:
```bash
chatti --doctor
```
Der Doctor prüft, ob alles funktioniert:
- API-Zugriff (Key gültig?)
- Internetverbindung
- Schreibrechte für Config- und Log-Verzeichnisse
- Erreichbare Modelle (z. B. gpt-4o, gpt-5)

Wenn alles grün ist: Glückwunsch, dein Chatti lebt! 🎉

### 🧩 Modelle & Grenzen
Die Modelle unterscheiden sich in Preis, Geschwindigkeit und „Wissensstand“:

| Modell | Geschwindigkeit | Wissensstand | Bemerkung |
|:--|:--:|:--:|:--|
| gpt-3.5-turbo | ⚡⚡⚡ | 2021 | schnell & günstig |
| gpt-4-turbo | ⚡⚡ | 2023 | solide Allround-Wahl |
| gpt-4o | ⚡⚡⚡ | Ende 2024 | multimodal & robust |
| gpt-5 | ⚡ | 2025 | neue Architektur, stabil & produktionsreif |
| gpt-5-realtime | ⚡⚡ | 2025 | interaktive Preview-Variante (Beta) |

> 💡 *Tipp:* Du kannst das aktive Modell jederzeit wechseln mit:
> `chatti --model gpt-5`

Und falls etwas nicht klappt:
```bash
chatti --whoami
```
zeigt dir, welcher Benutzer aktiv ist, welche Konfigurationspfade gelten –
und ob Chatti deinen API-Key korrekt geladen hat.

---

## (1) 🔐 Sicherheit & Kryptographie

Chatti speichert so wenig Daten wie möglich – und das, was er speichert, bleibt lokal.
Dieses Kapitel erklärt, was bei der Ersteinrichtung passiert, wie Passwörter behandelt werden, und was mit deinen Daten (auch bei OpenAI) geschieht.

---

### 🔑 Admin-PIN & Ersteinrichtung

Beim allerersten Start prüft Chatti, ob eine Admin-PIN hinterlegt ist.
Diese PIN schützt administrative Funktionen wie Benutzeranlage, Daten-Reset oder Log-Zugriff.
Wenn keine PIN existiert, wirst du automatisch aufgefordert, eine zu setzen.

> **Hinweis:** Die Admin-PIN wird niemals im Klartext gespeichert, sondern per
> **PBKDF2 + Fernet** verschlüsselt.
> Das bedeutet: selbst wer Zugriff auf deine Konfigurationsdateien hat, kann daraus keine gültige PIN rekonstruieren.

---

### 🧩 Passwort-Kriterien

Beim Anlegen eines Benutzers verlangt Chatti ein **Master-Passwort**, das mindestens **12 Zeichen** lang ist.
Kurze oder triviale Kennwörter werden abgewiesen.
Intern wird die Passwortstärke zusätzlich mit der Bibliothek **zxcvbn** (Dropbox-Algorithmus) bewertet (optional, bei Installation des entsprechenden Python-Moduls).

Empfohlen werden **Passphrasen** wie z.B.:
```
segelboot-farn-wolkenschloss
donald-t-is-120%-the-new-pope!
```

Diese sind sicherer und leichter zu merken als zufällige Buchstabenfolgen.

> 🔒 Das Master-Passwort schützt deine verschlüsselten Dateien (API-Keys, History, Attachments, etc.).
> Ohne dieses Passwort sind die Daten **unlesbar** – selbst für dich.

---

### 🌍 Was passiert mit deinen Daten bei OpenAI?

Alles, was du in Chatti schreibst, wird **nur zur Laufzeit** an die OpenAI-API gesendet.
- Standardmäßig werden Eingaben **nicht** zum Training verwendet (laut OpenAI-Policy).
- Deine Inhalte werden temporär gespeichert, um Antwortqualität und Missbrauchserkennung zu gewährleisten.
- API-Calls erfolgen **ausschließlich über HTTPS** mit TLS 1.3.

Mehr unter: [https://platform.openai.com/docs/data-usage](https://platform.openai.com/docs/data-usage)

---

### 🧠 Kryptographie im Client

Chatti verschlüsselt lokal alle sensiblen Daten mit **Fernet (AES-128 CBC + HMAC)**.
Die Schlüssel werden aus deinem Master-Passwort mit **PBKDF2 (SHA-256)** abgeleitet.
Dadurch ergibt sich:

| Bereich | Speicherung | Verschlüsselung |
|:--|:--|:--|
| API-Key | `chatti_secrets` | Fernet |
| User-Config | `users/<uid>/conf/` | Klartext (nicht-kritisch) |
| History & Inputs | `users/<uid>/data/` | Optional (config-abhängig) |
| Attachments | `users/<uid>/attachments/` | Klartext oder AES, je nach Typ |

> 💡 Chatti hat **keinen Cloud-Sync**, keine Telemetrie, kein Tracking.
> Jede Datei bleibt auf deinem System – transparent, nachvollziehbar und exportierbar.

---

**Kurz gesagt:**
Chatti arbeitet nach dem Prinzip:
> _„So viel Schutz wie nötig, so wenig Cloud wie möglich.“_

---

### 📂 Dateipfade & Aliasse

Chatti legt für jeden Benutzer eine eigene, klar getrennte Datenstruktur an.
Standardmäßig liegen diese Daten in deinem Benutzerverzeichnis unter:

| Bereich | Pfad | Beschreibung |
|:--|:--|:--|
| Konfiguration | `~/.config/chatti` | globale Einstellungen, z. B. Sprache oder Log-Level |
| Benutzerdaten | `~/.local/share/chatti/users/<UID>` | alles Benutzerbezogene (History, Attachments, Support, etc.) |
| Temporäre Dateien | `~/.cache/chatti` | PDF-Cache, Bild-Vorschauen |
| Logdateien | `~/.local/state/chatti/logs` | technische Diagnoseinfos |
| Symbolischer Link („Portal“) | `~/chatti_<UID>` | direkter Schnellzugriff für den jeweiligen Benutzer |

Der symbolische Link (Portal) verweist auf die jeweils aktive Benutzerumgebung.
Er wird beim Anlegen eines neuen Benutzers automatisch erstellt und enthält praktische Verweise:
```
~/chatti_/
├── Config  → ~/.config/chatti
├── Data    → ~/.local/share/chatti/users//data
├── Docs    → ~/.local/share/chatti/docs
├── Support → ~/.local/share/chatti/users//support
├── Attachments → ~/.local/share/chatti/users//attachments
└── History.jsonl → ~/.local/share/chatti/users//data/history.jsonl
```

## (2) 💬 Bedienung & Oberfläche

(Platzhalter – folgt in Kürze)

- Textbasiertes UI (TUI) mit Log-Panel und Eingabezeile
- Grundprinzip: Chat‑Nachrichten + Befehle (`:`‑Präfix)
- Eingaben abschicken: `Shift-Enter`
- Mehrzeilige Eingaben mit `Enter`
- Farbcodierung der Rollen (User / System / Assistant)
- Tastaturkürzel: `Ctrl+C` (Abbrechen), `:clear`, `:quit`
---

## (3) 📎 Upload & Attachments

(Platzhalter – folgt in Kürze)


- Unterstützte Dateitypen: `.txt`, `.pdf`, `.png`, `.jpg`, `.json`, `.csv`
- Upload: `:attach <filename>` oder Drag‑and‑Drop (falls Terminal unterstützt)
- Dateigröße: Limit laut Config (`max_upload_mb`)
- PDF‑Texterkennung (pdf2image + PyPDF2 + Pillow)
- Sicherheit: Dateien werden **lokal** gespeichert, keine Cloud‑Übertragung
- Inline‑Darstellung per `data:`‑URLs möglich

---

## (4) ⚡ Autocompletion & Befehle

(Platzhalter – folgt in Kürze)

- Command‑Mode mit `:` (z. B. `:search`, `:goto`, `:dump`)
- Autovervollständigung mit `Alt<Option(auf dem Mac)> Pfeil rechts`
- Häufige Befehle:
  - `:help` – Übersicht aller Commands
  - `:clear` – Verlauf löschen (nur Anzeige)
  - `:search <text>` – Volltextsuchen
  - `:goto N` – Springt zu Treffer Nr. N
  - `:history-dump` – Exportiert History (verschlüsselt/Plaintext)
  - `:whoami` – zeigt aktuellen Benutzer und aktive Konfiguration
  - `:remove-my-account` – löscht Konto & Daten
- Erweiterbarkeit: künftige Plugin‑Schnittstelle

---

## (5) 🧾 History, Dumps & Logging

(Platzhalter – folgt in Kürze)

- History‑Dateien liegen unter:
  `~/.local/share/chatti-cli/users/<uid>/history.jsonl`
- Speicherung wahlweise **verschlüsselt** oder **unverschlüsselt**
- Dump‑Funktion (`:history-dump` / `:history-dump-plain`)
- Suchmodi:
  - `and:` / `or:` / `rx:` (RegEx‑Modus)
  - Treffer nummeriert → `:goto <Nr>` möglich
- Log‑Dateien und Debug‑Ausgabe: `~/.local/share/chatti-cli/logs`
- History‑Management: automatische Rotation optional

---

## (6) 🧭 Diagnose, Doctor & Systembefehle

(Platzhalter – folgt in Kürze)

- `--doctor` prüft Installation, API‑Zugriff, Modelle & Pfade
- `--whoami` zeigt aktive UID, Session‑Pfad und Modell
- Ausgabe im TUI: `:whoami`
- Smoke‑Test: Kurzanalyse von API‑Key & Verbindung
- Logging‑Check: prüft Schreibrechte & Loggröße
- Diagnoseberichte werden lokal in `/support` abgelegt (Admin‑Leserechte)

---

## (7) 🧑‍💼 Administration & Multi‑User

(Platzhalter – folgt in Kürze)

- Admin‑PIN zur Erstinstallation
- Benutzerverwaltung (Anlegen, Löschen, Aktualisieren)
- Rollenkonzept (Admin / User)
- Support‑Ordner: `/users/<uid>/support`
- Ticket‑System (automatische Meldung bei Fehlern)
- Backup‑Strategien (History & Attachments)
- Optional: zentrale Multi‑User‑Instanz auf Server (Docker‑fähig)

---

© 2025 Chatti Client — Lizenz: MIT
Dieses Handbuch darf frei kopiert und erweitert werden.
