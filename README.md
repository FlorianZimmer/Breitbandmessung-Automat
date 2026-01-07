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
- `--enforce-calendar-gap` (erzwingt mindestens 1 Tag Pause zwischen Messtagen)

Beispiele:

```powershell
python .\breitbandmessung_automate_stateful.py --day-goal 10 --campaign-goal 30 --enforce-calendar-gap
python .\breitbandmessung_automate_stateful.py --run-today
```

## Dateien, die lokal entstehen

- `bbm_state.json` (Fortschritt/Status)
- `breitbandmessung_automate_stateful.log` (Log)
- `bbm_ui_dump_*.txt` (UI-Dumps bei Fehlern)

