// Прогон app.js без браузера: минимальный DOM + реальный API.
const fs = require("fs");

const BASE = "http://127.0.0.1:8080";
const store = new Map();

function makeEl(id) {
  if (!store.has(id)) {
    store.set(id, {
      id,
      innerHTML: "",
      textContent: "",
      className: "",
      value: "",
      hidden: false,
      dataset: {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      addEventListener() {},
      setAttribute() {},
      querySelectorAll: () => [],
      querySelector: () => null,
      appendChild() {},
      insertAdjacentHTML(pos, html) {
        this.innerHTML += html;
      },
      focus() {},
      reset() {},
    });
  }
  return store.get(id);
}

global.document = {
  getElementById: makeEl,
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener() {},
  createElement: () => makeEl("tmp" + Math.random()),
  body: makeEl("body"),
};
global.window = { addEventListener() {}, location: { href: "" } };
global.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
global.IntersectionObserver = class { observe() {} disconnect() {} };
global.ResizeObserver = class { observe() {} disconnect() {} };
global.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
global.requestAnimationFrame = () => 0;
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.navigator = { language: "ru", clipboard: { writeText: async () => {} } };

const realFetch = global.fetch;
global.fetch = (url, options) => realFetch(BASE + url, { cache: "no-store", ...options });

process.on("unhandledRejection", (err) => {
  console.log("НЕОБРАБОТАННАЯ ОШИБКА:", err && err.message ? err.message : err);
  if (err && err.stack) console.log(String(err.stack).split("\n").slice(0, 4).join("\n"));
});

let source = fs.readFileSync("app/web/app.js", "utf8");
source += "\nglobalThis.__loadTasks = loadTasks;\nglobalThis.__state = state;";
eval(source);

(async () => {
  try {
    await globalThis.__loadTasks(false);
  } catch (error) {
    console.log("ОШИБКА loadTasks:", error.message);
    console.log(String(error.stack).split("\n").slice(0, 5).join("\n"));
  }
  const list = makeEl("taskList");
  const stats = makeEl("stats");
  console.log("total в состоянии:", globalThis.__state.total);
  console.log("длина HTML списка:", list.innerHTML.length);
  console.log("первые 300 символов:", list.innerHTML.slice(0, 300).replace(/\s+/g, " "));
  console.log("сводка:", stats.innerHTML.replace(/\s+/g, " ").slice(0, 200));
  process.exit(0);
})();

