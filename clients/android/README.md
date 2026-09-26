# Android-App (Phase 6)

Kotlin + Jetpack Compose, **Pipecat Kotlin-SDK** (RTVI) für Audio und Verbindung.

## Geplanter Aufbau

```
app/
  MainActivity.kt          Chat-Ansicht, Push-to-Talk, Wolken-Symbol
  JarvisConnection.kt      Pipecat-Client → wss://<server>/ws/client?token=…
  assistant/
    JarvisVoiceInteractionService.kt   als Standard-Assistent (langer Druck Power/Home)
  push/
    UnifiedPushReceiver.kt  Timer/Erinnerungen über ntfy (selbst gehostet)
  widget/
    JarvisWidget.kt         Homescreen-Knopf
  settings/                 Server, Token, optionales On-Device-Wake-Word
```

## Voraussetzungen
- Erreichbarkeit unterwegs über **WireGuard** (Unraid) – keine offenen Ports.
- HTTPS/WSS mit eigener CA oder Let's-Encrypt-Zertifikat.
- Gerät in Jarvis vom Typ `android` anlegen.
