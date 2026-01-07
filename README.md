# Breitbandmessung-Automat

[![CI](https://github.com/FlorianZimmer/Breitbandmessung-Automat/actions/workflows/ci.yml/badge.svg)](https://github.com/FlorianZimmer/Breitbandmessung-Automat/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/FlorianZimmer/Breitbandmessung-Automat?display_name=tag&sort=semver)](https://github.com/FlorianZimmer/Breitbandmessung-Automat/releases/latest)
[![Download EXE](https://img.shields.io/badge/Download-EXE-blue)](https://github.com/FlorianZimmer/Breitbandmessung-Automat/releases/latest/download/Breitbandmessung-Automat.exe)

Automatisiert die Windows-App **Breitbandmessung** (Bundesnetzagentur / BNetzA) per UI-Automation, um Messkampagnen über mehrere Tage hinweg mit den vorgegebenen Zeitabständen durchzuführen.

Offizielles Tool: [breitbandmessung.de](https://www.breitbandmessung.de/)

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

## Alle Parameter (mit Beispielen)

Tipp: Alle Optionen anzeigen: `--help`

### Dateien / Ziele

- `--state-file bbm_state.json` (Default: `bbm_state.json`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --state-file "C:\Breitbandmessung-Automat\bbm_state.json"`
- `--day-goal 10` / `--campaign-goal 30` (Overrides)
  - Beispiel: `.\Breitbandmessung-Automat.exe --day-goal 10 --campaign-goal 30`

### Resume / Seed

- `--skip-initial-wait` / `--no-skip-initial-wait` (Default: `--skip-initial-wait`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --no-skip-initial-wait`
- `--seed-day-done X` (setzt heutigen Fortschritt einmalig)
  - Beispiel: `.\Breitbandmessung-Automat.exe --seed-day-done 10`
- `--seed-campaign-done Y` (setzt Kampagnen-Fortschritt einmalig)
  - Beispiel: `.\Breitbandmessung-Automat.exe --seed-campaign-done 10`
- `--try-read-ui-progress` (liest best-effort `6/10` und `6/30` aus der UI)
  - Beispiel: `.\Breitbandmessung-Automat.exe --try-read-ui-progress`

### Laufmodus / Regeln

- `--run-until-campaign-done` / `--no-run-until-campaign-done` (Default: `--run-until-campaign-done`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --no-run-until-campaign-done`
- `--run-today` (Alias für `--no-run-until-campaign-done`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --run-today`
- `--enforce-calendar-gap` / `--no-enforce-calendar-gap` (Default: `--enforce-calendar-gap`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --no-enforce-calendar-gap`
- `--wait-calendar-gap` (wenn Kalendertag-Abstand blockiert: schlafen statt beenden)
  - Beispiel: `.\Breitbandmessung-Automat.exe --wait-calendar-gap`
- `--force` (ignoriert Calendar-Gap Block)
  - Beispiel: `.\Breitbandmessung-Automat.exe --force`

### Zeitfenster / Scheduling

- `--day-start HH:MM` / `--day-end HH:MM` (Default: `07:00` bis `23:00`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --day-start 07:00 --day-end 22:00`
- `--day-start-jitter-minutes N` (Default: `45`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --day-start-jitter-minutes 0`
- `--next-start "<HH:MM|YYYY-MM-DD HH:MM>"` (setzt den Start der *nächsten* Messung)
  - Beispiele: `.\Breitbandmessung-Automat.exe --next-start "20:00"` / `.\Breitbandmessung-Automat.exe --next-start "2026-01-09 10:00"`
- `--schedule-cron "<min> <hour> * * *"` (eigener Startplan; nur Minute+Stunde)
  - Beispiele: `.\Breitbandmessung-Automat.exe --schedule-cron "0 7,10,20 * * *"` / `.\Breitbandmessung-Automat.exe --schedule-cron "*/15 7-22 * * *"`

### Abstände / Sicherheit

- `--min-gap-buffer-seconds N` (Default: `120`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --min-gap-buffer-seconds 300`
- `--post-measurement-settle-seconds N` (Default: `30`)
  - Beispiel: `.\Breitbandmessung-Automat.exe --post-measurement-settle-seconds 60`
- `--random-seed N` (reproduzierbares Scheduling)
  - Beispiel: `.\Breitbandmessung-Automat.exe --random-seed 12345`

## Dateien, die lokal entstehen

- `bbm_state.json` (Fortschritt/Status)
- `<programmname>.log` (Log; z. B. `breitbandmessung_automate_stateful.log` oder `Breitbandmessung-Automat.log`)
- `bbm_ui_dump_*.txt` (UI-Dumps bei Fehlern)

<details><summary>Suchbegriffe</summary>
Breitbandmessung, Bundesnetzagentur, BNetzA, Messkampagne, Speedtest, Internetgeschwindigkeit, Windows Automation, pywinauto
</details>
