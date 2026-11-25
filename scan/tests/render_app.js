// Runs the app template's script on JSON from stdin with a minimal DOM; prints each tab's HTML as JSON.
const fs = require("fs"), path = require("path"), vm = require("vm");
const tpl = fs.readFileSync(path.join(__dirname, "..", "app_template.html"), "utf8");
const script = tpl.match(/<script>([\s\S]*?)<\/script>/)[1];
const els = { "app-data": { textContent: fs.readFileSync(0, "utf8") } };
const document = {
  getElementById: (id) => (els[id] = els[id] || {}),
  querySelectorAll: () => [],
};
vm.runInNewContext(script, { document, window: { scrollTo() {} } });
console.log(JSON.stringify(Object.fromEntries(["today", "paper", "stocks", "crypto"].map((id) => [id, els[id].innerHTML]))));
