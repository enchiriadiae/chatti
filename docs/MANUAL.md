# Chatti – CLI Client Handbuch

Chatti ist ein Terminal-basierter Client für OpenAI-Modelle.
Er bietet eine einfache TUI (Text User Interface) mit History, Attachments, Autocomplete und Diagnose-Tools.

---

## Installation & Start

```bash
# Ausführbar machen (falls noch nicht):
chmod +x ./chatti

# Starten:
./chatti

Vor dem Start prüft Chatti die Internetverbindung.
Die Prüfung kann umgangen werden mit der Umgebungsvariablen CHATTI_SKIP_NETCHECK.
Gib' dazu ein:
CHATTI_SKIP_NETCHECK=1 ./chatti

# Konfigurationsdatei

Chatti liest Einstellungen aus der Datei chatti.conf (im Projekt-Root).
Kommentare beginnen mit # oder ;.

Wichtige Optionen:
	•	show_welcome = true
Zeigt beim Start Tipps zur Bedienung.
	•	system_prompt = "Du bist hilfsbereit und knapp."
Definiert den Basis-Prompt für alle Antworten.
	•	system_prompt_style = knapp | freundlich | technisch | coach | humor
Vordefinierte Stile, wenn kein eigener Prompt angegeben ist.
	•	system_prompt_file = prompts/mein_prompt.txt
Optional: Längere Prompts aus externer Datei laden.
	•	hold_history_file = true
History zwischen Sitzungen speichern.

⸻

# Bedienung

Eingabe
	•	Enter – Nachricht senden
	•	Shift+Enter – Neue Zeile einfügen
	•	TAB – Fokus auf den Senden-Button
	•	Alt+↑ / Alt+↓ – Eingabe-Historie durchblättern
	•	Ctrl+F – Suchmodus in der Ausgabe
	•	Esc – Suchmodus verlassen
	•	Alt/Strg+→ – Autocomplete für :/-Kommandos

⸻

# Kommandos

Kommandos beginnen mit : oder /.
Autocomplete (Alt/Strg+→ ) zeigt verfügbare Befehle.

Beispiele:
	•	:doctor – Diagnose starten
	•	:show-prompt – Aktiven System-Prompt anzeigen
	•	:attach-add <pfad> – Datei anhängen
	•	:attach-list – Anhänge auflisten
	•	:attach-clear – Anhänge löschen
	•	:exit oder :quit – Programm beenden

./chatti [OPTIONEN]

	•	--verify – Smoke-Test beim Start erzwingen (dauert ein paar Sekunden)
	•	--reset-auth[=soft|hard] – Auth-Daten zurücksetzen
	•	--doctor oder --doc – Diagnose starten
	•	-man oder --manual – Dieses Handbuch anzeigen
	•	-h oder --help – Kurzhilfe anzeigen

Tipps & Hinweise
	•	Secrets (API-Key) werden verschlüsselt gespeichert.
	•	Für längere Texte empfiehlt es sich, Prompts in eine Datei auszulagern und über system_prompt_file zu laden.
	•	Die History wird in history.jsonl gespeichert (JSON-Lines Format).


## Admin-PIN

Der Admin-PIN schützt sensible CLI-Aktionen (z. B. `--user-add`, `--user-remove`).
Beim ersten Start ohne PIN wird er einmalig abgefragt.

- Setzen:         `chatti --admin-set-pin`
- Ändern:         `chatti --admin-change-pin`
- Verifizieren:   automatisch vor geschützten Kommandos (3 Versuche)

Intern wird der Admin-PIN nicht im Klartext gespeichert. Stattdessen liegt ein scrypt-Hash
(z. B. mit Parametern n=16384, r=8, p=1, dklen=32) + Salt in `admin_pin.json`. Ein Dieb kann aus
dieser Datei den PIN nicht zurückrechnen, aber die App kann Eingaben dagegen prüfen.

Hinweise:
- `--user-add` und `--user-remove` sind Admin-geschützt.
- Beim Abbruch (Ctrl+C) wird die Aktion sauber beendet.
