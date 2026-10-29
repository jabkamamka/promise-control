/* Пасхалка на клавишу Z: мини-игра «Обещание-шутер».
   Подключается отдельным файлом, чтобы не трогать app.js. */

(function () {
  const POOL_PROMISES = [
    "Перезвоню через час",
    "Отправлю счёт на почту",
    "Уточню и вернусь с ответом",
    "Наберу вас завтра в 10:00",
    "Вышлю договор сегодня",
    "Согласую скидку до вечера",
  ];
  const POOL_TRAPS = ["Не перезвоню", "Не смогу", "Не вышлю счёт", "Ничего не обещаю"];
  const TOTAL_CELLS = 9;
  const ROUND_SECONDS = 30;

  const state = { running: false, score: 0, left: ROUND_SECONDS, timer: null, best: 0 };

  const $ = (id) => document.getElementById(id);
  const modal = () => $("arcadeModal");
  const field = () => $("arcadeField");

  function readBest() {
    try {
      state.best = Number(localStorage.getItem("promise-arcade-best") || 0);
    } catch (error) {
      state.best = 0;
    }
    $("arcadeBest").textContent = String(state.best);
  }

  function saveBest() {
    if (state.score <= state.best) return;
    state.best = state.score;
    try {
      localStorage.setItem("promise-arcade-best", String(state.best));
    } catch (error) {
      /* приватный режим — рекорд просто не запомнится */
    }
    $("arcadeBest").textContent = String(state.best);
  }

  function randomCard(exclude) {
    const all = [
      ...POOL_PROMISES.map((text) => ({ text, ok: true })),
      ...POOL_TRAPS.map((text) => ({ text, ok: false })),
    ];
    const free = all.filter((card) => !exclude.has(card.text));
    const pool = free.length ? free : all;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function makeCell() {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "arcade-cell";
    cell.addEventListener("click", () => onCell(cell));
    fillCell(cell);
    return cell;
  }

  function fillCell(cell) {
    const used = new Set(
      [...document.querySelectorAll(".arcade-cell")]
        .filter((other) => other !== cell)
        .map((other) => other.textContent)
    );
    const card = randomCard(used);
    cell.dataset.ok = card.ok ? "1" : "0";
    cell.textContent = card.text;
    cell.classList.remove("hit", "miss");
  }

  function onCell(cell) {
    if (!state.running) return;
    const ok = cell.dataset.ok === "1";
    if (ok) {
      state.score += 1;
      cell.classList.add("hit");
    } else {
      state.score = Math.max(0, state.score - 1);
      cell.classList.add("miss");
    }
    $("arcadeScore").textContent = String(state.score);
    setTimeout(() => fillCell(cell), 140);
  }

  function renderField() {
    const container = field();
    container.innerHTML = "";
    for (let i = 0; i < TOTAL_CELLS; i += 1) container.appendChild(makeCell());
  }

  function tick() {
    state.left -= 1;
    $("arcadeTime").textContent = String(state.left);
    if (state.left <= 0) finish();
  }

  function start() {
    state.running = true;
    state.score = 0;
    state.left = ROUND_SECONDS;
    $("arcadeScore").textContent = "0";
    $("arcadeTime").textContent = String(ROUND_SECONDS);
    $("arcadeHint").textContent = "";
    $("arcadeStart").textContent = "Заново";
    clearInterval(state.timer);
    state.timer = setInterval(tick, 1000);
    renderField();
  }

  function finish() {
    state.running = false;
    clearInterval(state.timer);
    saveBest();
    $("arcadeHint").textContent = `Готово: ${state.score} из ${TOTAL_CELLS * 3}. Рекорд — ${state.best}.`;
    $("arcadeStart").textContent = "Ещё раз";
  }

  function open() {
    modal().classList.remove("hidden");
    readBest();
    start();
  }

  function close() {
    state.running = false;
    clearInterval(state.timer);
    modal().classList.add("hidden");
  }

  function isTyping(target) {
    if (!target) return false;
    const tag = target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
  }

  document.addEventListener("keydown", (event) => {
    // Z в русской раскладке даёт «я» — поддерживаем оба варианта.
    const isZ = event.code === "KeyZ" || event.key === "z" || event.key === "Z" || event.key === "я" || event.key === "Я";
    if (!isZ || event.ctrlKey || event.altKey || event.metaKey) return;
    if (isTyping(event.target)) return;
    event.preventDefault();
    if (modal().classList.contains("hidden")) open();
    else start();
  });

  $("closeArcade").addEventListener("click", close);
  $("arcadeStart").addEventListener("click", start);
  modal().addEventListener("click", (event) => {
    if (event.target.id === "arcadeModal") close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") close();
  });

  readBest();
})();
