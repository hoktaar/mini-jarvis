# Android Auto (Phase 7)

Teil der Android-App, **Car App Library**, Kategorie `androidx.car.app.category.IOT`.

- `JarvisCarAppService` + `GridTemplate`: Knopf „Jarvis fragen“ + Favoriten
  (Skripte/Container mit `car_allowed: true`).
- Sprache über `CarAudioRecord` (Automikrofon) → gleiche RTVI-Verbindung,
  Antwort über die Autolautsprecher, kurzer Text im `MessageTemplate`.
- Gerätetyp `android_auto`: Die Policy sperrt Skripte ohne `car_allowed`.
- Kein Wake-Word im Auto (Lenkradtaste gehört Google) – Start per Tipp.
- Installation ohne Play Store: in Android Auto die Entwicklereinstellungen
  öffnen und **„Unbekannte Quellen“** aktivieren.
