import fs from "node:fs";

const targets = await fetch("http://127.0.0.1:9333/json/list").then((response) => response.json());
const target = targets.find((item) => item.type === "page");
if (!target) throw new Error("No Chrome page target found");

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let messageId = 0;
const pending = new Map();
socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(message.error.message));
  else resolve(message.result);
});

function send(method, params = {}) {
  const id = ++messageId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const login = JSON.parse(fs.readFileSync("/tmp/charcha-login-check.json", "utf8"));
const targetPath = process.env.TARGET_PATH || "/record";
const screenshotName = process.env.SCREENSHOT_NAME || "record";

await send("Page.enable");
await send("Runtime.enable");
await send("Page.navigate", { url: "http://localhost:3200/login" });
await wait(1000);
await send("Runtime.evaluate", {
  expression: `localStorage.setItem("charchaToken", ${JSON.stringify(login.token)})`,
});
await send("Page.navigate", { url: `http://localhost:3200${targetPath}` });
await wait(1600);

for (const viewport of [
  { name: "desktop", width: 1440, height: 1000, mobile: false },
  { name: "mobile", width: 390, height: 844, mobile: true },
]) {
  await send("Emulation.setDeviceMetricsOverride", {
    width: viewport.width,
    height: viewport.height,
    deviceScaleFactor: 1,
    mobile: viewport.mobile,
  });
  await wait(300);
  const capture = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  fs.writeFileSync(`/tmp/charcha-${screenshotName}-${viewport.name}.png`, Buffer.from(capture.data, "base64"));
}

const page = await send("Runtime.evaluate", {
  expression: `JSON.stringify({ title: document.title, url: location.href, text: document.body.innerText, width: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth })`,
  returnByValue: true,
});
console.log(page.result.value);
socket.close();
