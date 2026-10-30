// Прогон analytics.js без браузера: минимальный DOM + реальный API.
const fs = require("fs");

const BASE = "http://127.0.0.1:8080";
const store = new Map();

function makeEl(id) {
  if (!store.has(id)) {
    store.set(id, {
      id,
      innerHTML: "",
      textContent: "",
      href: "",
      hidden: false,
      dataset: {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      addEventListener() {},
      querySelectorAll: () => [],
      setAttribute() {},
      style: {},
    });
  }
  return store.get(id);
}

global.document = { getElementById: makeEl, querySelectorAll: () => [], addEventListener() {} };
global.window = { addEventListener() {}, location: { href: "" } };
global.setInterval = () => 0;
global.MutationObserver = class { observe() {} disconnect() {} };

const realFetch = global.fetch;
global.fetch = (url, options) => realFetch(BASE + url, { cache: "no-store", ...options });

process.on("unhandledRejection", (err) => {
  console.log("НЕОБРАБОТАННАЯ ОШИБКА:", err && err.message);
  if (err && err.stack) console.log(String(err.stack).split("\n").slice(0, 5).join("\n"));
});

try {
  eval(fs.readFileSync("app/web/analytics.js", "utf8"));
} catch (error) {
  console.log("ОШИБКА ПРИ ЗАГРУЗКЕ:", error.message);
  console.log(String(error.stack).split("\n").slice(0, 5).join("\n"));
  process.exit(1);
}

setTimeout(() => {
  for (const id of ["kpis", "periods", "verify", "closeTime", "types", "operators", "chart", "foot", "stamp"]) {
    const el = makeEl(id);
    console.log(`${id.padEnd(10)} длина: ${String(el.innerHTML || el.textContent).length}`);
  }
  process.exit(0);
}, 2500);
