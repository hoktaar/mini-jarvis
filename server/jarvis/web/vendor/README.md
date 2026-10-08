# Vendored

Lokal gebündelt, damit PWA und Verwaltung ohne CDN/Internet laufen.

| Datei | Inhalt | Lizenz |
|---|---|---|
| `pipecat.js` | @pipecat-ai/client-js 1.13.1 + @pipecat-ai/websocket-transport 1.7.2 | BSD-2-Clause (Daily) |
| `esptool.js` | esptool-js 0.7.0 (Web-Serial-Flasher, Stub-Flasher eingebettet) | Apache-2.0 (Espressif) |

Wichtig: Die PWA nutzt `WavMediaManager` (lokal). Der Standard-Media-Manager des
WebSocket-Transports (Daily) lädt Code von `c.daily.co` nach und hängt ohne Internet.

Neu bauen:

```bash
npm i @pipecat-ai/client-js@1.13.1 @pipecat-ai/websocket-transport@1.7.2 esptool-js@0.7.0 esbuild
echo 'export { PipecatClient } from "@pipecat-ai/client-js";
export { WebSocketTransport, ProtobufFrameSerializer, WavMediaManager } from "@pipecat-ai/websocket-transport";' > pipecat-entry.js
npx esbuild pipecat-entry.js --bundle --format=esm --minify --target=es2020 --outfile=pipecat.js
echo 'export { ESPLoader, Transport } from "esptool-js";' > esptool-entry.js
npx esbuild esptool-entry.js --bundle --format=esm --minify --target=es2020 --outfile=esptool.js
```
