// Runs the app template's script with a fake Claude desktop API. stdin: {data, state, exec}.
// Prints the live-update line and the Today tab after the promises settle.
const fs = require("fs"), path = require("path"), vm = require("vm");
const tpl = fs.readFileSync(path.join(__dirname, "..", "app_template.html"), "utf8");
const script = tpl.match(/<script>([\s\S]*?)<\/script>/)[1];
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const els = { "app-data": { textContent: JSON.stringify(input.data) } };
const el = (id) => (els[id] = els[id] || { innerHTML: "", insertAdjacentHTML(_, h) { this.innerHTML += h; } });
const document = { getElementById: el, querySelectorAll: () => [], visibilityState: "visible",
  createElement: () => ({ getContext: () => ({ fillRect() {}, beginPath() {}, arc() {}, fill() {} }), toDataURL: () => "data:image/png;base64," }) };
let execs = 0;
const desktop = {
  install: { state: async () => "installed" },
  permissions: { state: async () => input.state, manage: async () => {} },
  os: { platform: async () => "win32" },
  app: { dock: { setIcon: async () => ({ written: true }) } },
  window: { setOptions: async () => ({ applied: "now" }) },
  childProcess: { exec: async () => { execs++; if (input.exec === "EPERM") throw new Error("EPERM: refused"); return input.exec; } },
};
const window = { claude: { use: async () => desktop }, scrollTo() {} };
vm.runInNewContext(script, { document, window, location: { hash: "" }, setInterval: () => 1, setTimeout: () => 1, console });
setTimeout(() => console.log(JSON.stringify({ live: el("live").innerHTML, today: el("today").innerHTML, execs })), 50);
