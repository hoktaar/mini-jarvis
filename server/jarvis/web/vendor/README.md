# Vendored

`pipecat.js` = @pipecat-ai/client-js 1.13.1 + @pipecat-ai/websocket-transport 1.7.2 (BSD-2-Clause, Daily),
lokal gebündelt, damit die PWA ohne CDN läuft. Neu bauen:

```bash
npm i @pipecat-ai/client-js @pipecat-ai/websocket-transport esbuild
echo 'export { PipecatClient } from "@pipecat-ai/client-js";
export { WebSocketTransport, ProtobufFrameSerializer } from "@pipecat-ai/websocket-transport";' > entry.js
npx esbuild entry.js --bundle --format=esm --minify --target=es2020 --outfile=pipecat.js
```
