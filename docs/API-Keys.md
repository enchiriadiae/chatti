# 🔑 OpenAI API-Keys & Modellübersicht

Damit **Chatti** mit der OpenAI-API kommunizieren kann, benötigst du einen **gültigen API-Key**.  
Diese Datei erklärt, wie du ihn bekommst, wie die Abrechnung funktioniert und welche Modelle du verwenden kannst.

---

## 1️⃣ API-Key anlegen

1. Öffne die OpenAI-Plattform:  
   👉 [https://platform.openai.com](https://platform.openai.com)

2. Logge dich ein oder erstelle ein kostenloses Konto.  
   Anschließend findest du im Menü  
   **Settings → API Keys**  
   (oder direkt: [https://platform.openai.com/api-keys](https://platform.openai.com/api-keys))  
   die Möglichkeit, neue Schlüssel zu generieren.

3. Erstelle einen neuen Schlüssel, z. B. mit dem Namen  
   **chatti-desktop** oder **chatti-server**.  
   Der Schlüssel beginnt mit `sk-...` und wird dir **nur einmalig** angezeigt – kopiere ihn also sofort!

> 💡 **Tipp:** Lege pro Gerät oder Anwendung eigene Keys an.  
> Du kannst sie später gezielt widerrufen, ohne alles neu zu konfigurieren.

---

## 2️⃣ Sicherheit & Speicherung

Chatti fragt dich beim ersten Start automatisch nach diesem Schlüssel.  
Er wird anschließend **lokal verschlüsselt** gespeichert – zusammen mit deinem Benutzernamen und Master-Passwort.  
Ändern kannst du ihn jederzeit über:

```bash
chatti --user-update
```

🔐 Der Schlüssel liegt **nicht im Klartext**, sondern in der Datei  
`~/.local/share/chatti-cli/chatti_secrets`,  
verschlüsselt mit deinem Master-Passwort (PBKDF2 + Fernet).

---

## 3️⃣ Kosten, Tokens & Abrechnung

OpenAI verwendet ein **verbrauchsbasiertes Preismodell**:

| Modell | Eingabe | Ausgabe | Hinweis |
|:--|:--:|:--:|:--|
| **gpt-4o** | $0.005 / 1 000 Tokens | $0.015 / 1 000 Tokens | Allzweckmodell (Standard in Chatti) |
| **gpt-4-turbo** | $0.01 | $0.03 | Schneller, günstiger, leicht weniger Kontext |
| **gpt-3.5-turbo** | $0.0015 | $0.002 | Sehr günstig, für einfache Aufgaben |
| **gpt-4.1 / 4.5 preview** | $0.005–0.01 | $0.015–0.03 | Early-Access-Modelle (API-First) |
| **gpt-5-preview** | ca. $0.010 | ca. $0.030 | Hochleistungsmodell, Beta-Zugang nötig |

> 💡 1 000 Tokens entsprechen ca. 750 – 1 000 Wörtern.  
> Ein durchschnittlicher Chat kostet **weniger als 1 Cent**.

Du brauchst **kein Abo** – nur eine Zahlungsmethode (Kreditkarte, Guthaben oder Prepaid-Balance).

---

## 4️⃣ Wie kommst du an GPT-5?

GPT-5 ist derzeit (Stand 2025) noch **API-exklusiv**.  
Das bedeutet:

- Zugriff gibt’s **nur** über die [OpenAI Developer Platform](https://platform.openai.com/).  
- Du benötigst ein **reguläres API-Konto** (kein ChatGPT-Pro-Abo).  
- Wenn dein Key gültig ist, kannst du in Chatti einfach das Modell umstellen:

```bash
chatti --model gpt-5
```

> Wenn du eine Fehlermeldung bekommst („model not found“),  
> wurde dein Key noch nicht für GPT-5 freigeschaltet – das geschieht schrittweise.

---

## 5️⃣ Zeit-Horizont („Knowledge Cutoff“)

| Modell | Wissensstand | Bemerkung |
|:--|:--:|:--|
| **GPT-3.5** | ~ 2021 | veraltet, kein aktuelles Weltwissen |
| **GPT-4-turbo** | ~ 2023 | gute Allgemeinbasis |
| **GPT-4o / 4.1** | ~ Ende 2024 | aktuelles Wissen über gängige Themen |
| **GPT-5** | ~ Frühjahr 2025 | neuester Stand, bessere Logik und Codeverständnis |

> 🕰️ Modelle sind **nicht live mit dem Internet verbunden** – sie kennen also nur den Stand bis zum jeweiligen „cutoff date“.  
> In Chatti kann aber optional **Web-Suche** aktiviert werden (sofern implementiert).

---

## 6️⃣ Guthaben, Limits & Verbrauchskontrolle

- Neue Konten starten oft mit einem kleinen Testguthaben (zeitlich befristet).  
- Du kannst in den **Billing Settings** Limits oder monatliche Obergrenzen definieren.  
- Das aktuelle Nutzungs-Dashboard findest du unter:  
  👉 [https://platform.openai.com/usage](https://platform.openai.com/usage)

---

## 7️⃣ Fehlersuche bei API-Keys

| Fehlertext | Bedeutung | Lösung |
|:--|:--|:--|
| `invalid_api_key` | Key falsch eingegeben | Kopiere den gesamten Schlüssel neu (inkl. „sk-…“) |
| `insufficient_quota` | Guthaben leer | Kreditkarte oder Guthaben hinzufügen |
| `model_not_found` | Modell nicht verfügbar | Anderes Modell wählen (`gpt-4o` oder `gpt-3.5-turbo`) |
| `401 / 403` | Konto gesperrt oder Key widerrufen | Neuen Key erstellen |
| `connection_error` | Keine Internetverbindung | Verbindung oder Proxy prüfen |

---

© 2025 Chatti Client — Lizenz: MIT  
Dieses Dokument darf frei kopiert, verändert und weitergegeben werden, solange der Hinweis auf die ursprüngliche Quelle erhalten bleibt.
