// Minimal CDP probe: opens a URL in the already-running headless Edge and prints
// console errors, uncaught exceptions and a snippet of the rendered DOM.
//   node scripts/cdp-check.mjs http://127.0.0.1:8000/
const url = process.argv[2] || "http://127.0.0.1:8000/";
const base = "http://127.0.0.1:9222";

const page = await fetch(`${base}/json/new?${encodeURIComponent(url)}`, { method: "PUT" }).then((r) => r.json());
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
    return;
  }
  if (message.method === "Runtime.exceptionThrown") {
    console.log("EXCEPTION", JSON.stringify(message.params.exceptionDetails).slice(0, 2000));
  }
  if (message.method === "Log.entryAdded") {
    console.log("LOG", message.params.entry.level, message.params.entry.text);
  }
  if (message.method === "Runtime.consoleAPICalled") {
    console.log(
      "CONSOLE",
      message.params.type,
      JSON.stringify(message.params.args.map((argument) => argument.value ?? argument.description)).slice(0, 800)
    );
  }
});

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await new Promise((resolve) => setTimeout(resolve, 8000));

const evaluated = await send("Runtime.evaluate", {
  expression: `(() => ({
    title: document.title,
    rootLength: (document.getElementById('root') || {}).innerHTML?.length ?? -1,
    text: (document.body.innerText || '').slice(0, 400),
    scripts: [...document.scripts].map(s => s.src || 'inline')
  }))()`,
  returnByValue: true
});
console.log("PAGE", JSON.stringify(evaluated.result?.result?.value, null, 2));
ws.close();
