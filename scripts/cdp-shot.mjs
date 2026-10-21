// Screenshot a page through an already-running headless Edge (CDP).
//   node scripts/cdp-shot.mjs <url> <output.png> [width] [height]
import { writeFileSync } from "node:fs";

const [url, output, widthArg, heightArg] = process.argv.slice(2);
if (!url || !output) {
  console.error("usage: node scripts/cdp-shot.mjs <url> <output.png> [width] [height]");
  process.exit(1);
}
const width = Number(widthArg || 1600);
const height = Number(heightArg || 1200);
const base = "http://127.0.0.1:9222";

const page = await fetch(`${base}/json/new?${encodeURIComponent(url)}`, { method: "PUT" }).then((response) => response.json());
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));

let seq = 0;
const pending = new Map();
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = ++seq;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });

ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    pending.get(message.id)(message);
    pending.delete(message.id);
  }
});

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width,
  height,
  deviceScaleFactor: 1,
  mobile: false
});

const deadline = Date.now() + 20000;
while (Date.now() < deadline) {
  const checked = await send("Runtime.evaluate", {
    expression:
      "(() => { const root = document.getElementById('root'); return { ready: !!root && root.childElementCount > 0, text: (document.body.innerText || '').slice(0, 80) }; })()",
    returnByValue: true
  });
  if (checked.result?.result?.value?.ready) break;
  await new Promise((resolve) => setTimeout(resolve, 400));
}

await new Promise((resolve) => setTimeout(resolve, 1200));
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
writeFileSync(output, Buffer.from(shot.result.data, "base64"));
console.log("saved", output, width + "x" + height);

await fetch(`${base}/json/close/${page.id}`).catch(() => undefined);
ws.close();
