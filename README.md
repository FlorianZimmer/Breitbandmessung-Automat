# Breitbandmessung-Automat

Automatisiert die Windows-App **Breitbandmessung** (Bundesnetzagentur) per UI-Automation, um Messkampagnen über mehrere Tage hinweg mit den vorgegebenen Zeitabständen durchzuführen.

## Voraussetzungen

- Windows (UI-Automation via `pywinauto`)
- Python 3.10+ empfohlen
- Die Breitbandmessung-App ist installiert und kann gestartet werden
- Der PC muss während der Messungen entsperrt bleiben (UI-Automation)

## Installation

```powershell
python -m pip install -r requirements.txt
```

## Nutzung

Startet/führt Messungen aus und verwaltet den Fortschritt in einer State-Datei:

```powershell
python .\breitbandmessung_automate_stateful.py
```

Wichtige Parameter:

- `--state-file` (Default: `bbm_state.json`)
- `--day-goal` / `--campaign-goal` (z. B. `10` / `30`)
- `--day-start` / `--day-end` (tägliches Zeitfenster)
- `--run-today` (stoppt nach dem Tagesziel statt über mehrere Tage weiterzulaufen)
- `--enforce-calendar-gap` / `--no-enforce-calendar-gap` (Default: aktiviert; erzwingt mindestens 1 freien Kalendertag zwischen Messtagen)
- `--wait-calendar-gap` (wenn der Kalendertag-Abstand blockiert: nicht beenden, sondern bis zum frühesten Zeitpunkt schlafen)
- `--next-start` (Startzeit der nächsten Messung explizit setzen, z. B. `HH:MM` oder `YYYY-MM-DD HH:MM`)
- `--schedule-cron` (eigener Startplan im Cron-Stil: `"<min> <hour> * * *"`; nur Minute+Stunde)

Beispiele:

```powershell
python .\breitbandmessung_automate_stateful.py --day-goal 10 --campaign-goal 30 --enforce-calendar-gap
python .\breitbandmessung_automate_stateful.py --run-today
python .\breitbandmessung_automate_stateful.py --wait-calendar-gap
python .\breitbandmessung_automate_stateful.py --next-start "20:00"
python .\breitbandmessung_automate_stateful.py --schedule-cron "0 7,10,20 * * *"
```

## Dateien, die lokal entstehen

- `bbm_state.json` (Fortschritt/Status)
- `breitbandmessung_automate_stateful.log` (Log)
- `bbm_ui_dump_*.txt` (UI-Dumps bei Fehlern)
