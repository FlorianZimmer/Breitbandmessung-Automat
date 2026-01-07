# Breitbandmessung-Automat

Automatisiert die Windows-App **Breitbandmessung** (Bundesnetzagentur) per UI-Automation, um Messkampagnen über mehrere Tage hinweg mit den vorgegebenen Zeitabständen durchzuführen.

## Download (ohne Python)

Letztes Release (Windows `.exe`):  
[Releases (latest)](https://github.com/FlorianZimmer/Breitbandmessung-Automat/releases/latest)

Direkt-Download der aktuellen `.exe`:  
[Breitbandmessung-Automat.exe (latest)](https://github.com/FlorianZimmer/Breitbandmessung-Automat/releases/latest/download/Breitbandmessung-Automat.exe)

## Voraussetzungen

- Windows (UI-Automation via `pywinauto`)
- Die Breitbandmessung-App ist installiert und kann gestartet werden
- Der PC muss während der Messungen entsperrt bleiben (UI-Automation)

Wenn du die `.exe` nutzt, brauchst du **kein Python**.

## Installation (Python)

```powershell
python -m pip install -r requirements.txt
```

## Nutzung

### Nutzung per `.exe` (empfohlen)

1) Lade die `Breitbandmessung-Automat.exe` aus dem neuesten Release herunter.  
2) Lege sie am besten in einen eigenen Ordner (z. B. `C:\Breitbandmessung-Automat\`).  
3) Doppelklick startet das Programm.

Optional (mit Parametern) in PowerShell im selben Ordner:

```powershell
.\Breitbandmessung-Automat.exe
.\Breitbandmessung-Automat.exe --run-today
.\Breitbandmessung-Automat.exe --wait-calendar-gap
.\Breitbandmessung-Automat.exe --next-start "20:00"
.\Breitbandmessung-Automat.exe --schedule-cron "0 7,10,20 * * *"
```

### Nutzung per Python (Dev)

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
- `<programmname>.log` (Log; z. B. `breitbandmessung_automate_stateful.log` oder `Breitbandmessung-Automat.log`)
- `bbm_ui_dump_*.txt` (UI-Dumps bei Fehlern)
