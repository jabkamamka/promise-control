const API = "";

const state = {
  status: "",
  type: "",
  q: "",
  offset: 0,
  limit: 30,
  total: 0,
  tz: "Asia/Yekaterinburg",
  loadToken: 0,
};

const STATUS_LABELS = {
  created: "Создана",
  in_progress: "В работе",
  done: "Выполнена",
  overdue: "Просрочена",
};

const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

const SOURCE_LABELS = {
  rule: "правила",
  "custom-rule": "свой тип",
  llm: "ИИ",
};

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (el.className = "toast"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

/* ----------------------------- форматирование ----------------------------- */

const dayFmt = (iso) =>
  new Intl.DateTimeFormat("ru-RU", { timeZone: state.tz, day: "numeric", month: "short" }).format(new Date(iso));
const timeFmt = (iso) =>
  new Intl.DateTimeFormat("ru-RU", { timeZone: state.tz, hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
const dateKey = (date) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: state.tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(date);

function dueLabel(task) {
  const due = new Date(task.due_at);
  const now = new Date();
  const today = dateKey(now);
  const dueDay = dateKey(due);
  const tomorrow = dateKey(new Date(now.getTime() + 86400000));
  const time = timeFmt(task.due_at);
  let label;
  if (dueDay === today) label = `сегодня, ${time}`;
  else if (dueDay === tomorrow) label = `завтра, ${time}`;
  else label = `${dayFmt(task.due_at)}, ${time}`;

  if (task.effective_status === "overdue") {
    const diff = Math.abs(now - due) / 3600000;
    const ago = diff < 1 ? "меньше часа" : diff < 24 ? `${Math.round(diff)} ч` : `${Math.round(diff / 24)} дн`;
    return { text: `${label} · просрочено на ${ago}`, cls: "overdue" };
  }
  const hours = (due - now) / 3600000;
  return { text: label, cls: hours >= 0 && hours < 24 ? "soon" : "" };
}

/* --------------------------------- данные --------------------------------- */

async function loadHealth() {
  try {
    const health = await api("/health");
    state.tz = health.timezone || state.tz;
  } catch (error) {
    console.warn("health", error);
  }
}

async function loadStats() {
  try {
    const stats = await api("/api/v1/stats");
    const by = stats.by_status || {};
    $("stats").innerHTML = `
      <div class="stat"><b>${stats.tasks_total}</b><span>задач</span></div>
      <div class="stat danger"><b>${stats.overdue}</b><span>просрочено</span></div>
      <div class="stat"><b>${stats.calls_total}</b><span>звонков</span></div>
      <div class="stat ok"><b>${by.done ?? 0}</b><span>выполнено</span></div>
    `;
    return stats;
  } catch (error) {
    console.warn("stats", error);
    return null;
  }
}

async function loadCounts() {
  const keys = ["", "overdue", "created", "in_progress", "done"];
  const totals = await Promise.all(
    keys.map((key) =>
      api(`/api/v1/tasks?limit=1${key ? `&status=${key}` : ""}`)
        .then((data) => data.total)
        .catch(() => null)
    )
  );
  return Object.fromEntries(keys.map((key, index) => [key, totals[index]]));
}

function statusChips(counts) {
  const items = [
    { key: "", title: "Все", count: counts?.[""] },
    { key: "overdue", title: STATUS_LABELS.overdue, count: counts?.overdue },
    { key: "created", title: STATUS_LABELS.created, count: counts?.created },
    { key: "in_progress", title: STATUS_LABELS.in_progress, count: counts?.in_progress },
    { key: "done", title: STATUS_LABELS.done, count: counts?.done },
  ];
  $("statusChips").innerHTML = items
    .map(
      (item) => `
      <button class="chip ${state.status === item.key ? "active" : ""}" data-status="${item.key}">
        ${item.title}${item.count != null ? `<span class="count">${item.count}</span>` : ""}
      </button>`
    )
    .join("");
  $("statusChips")
    .querySelectorAll(".chip")
    .forEach((chip) =>
      chip.addEventListener("click", () => {
        state.status = chip.dataset.status;
        state.offset = 0;
        refresh();
      })
    );
}

async function loadTypes() {
  const types = await api("/api/v1/promise-types");
  const current = state.type;
  $("typeFilter").innerHTML =
    `<option value="">Все типы</option>` +
    types.map((t) => `<option value="${esc(t.code)}">${esc(t.title)}</option>`).join("");
  $("typeFilter").value = current;

  $("typesList").innerHTML = types
    .map(
      (t) => `
      <div class="type-item">
        <h3>
          ${esc(t.title)}
          <span class="badge ${t.is_builtin ? "created" : "type"}">${t.is_builtin ? "встроенный" : "свой"}</span>
          <span class="badge">${t.tasks_count} задач</span>
        </h3>
        <p>${esc(t.description || "Без описания")}</p>
        <div class="kw">${(t.keywords || []).map((k) => `<span>${esc(k)}</span>`).join("")}</div>
        ${
          t.is_builtin
            ? ""
            : `<div style="margin-top:10px"><button class="ghost" data-delete-type="${esc(t.code)}">Удалить тип</button></div>`
        }
      </div>`
    )
    .join("");

  $("typesList")
    .querySelectorAll("[data-delete-type]")
    .forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/api/v1/promise-types/${btn.dataset.deleteType}`, { method: "DELETE" });
          toast("Тип удалён");
          await loadTypes();
        } catch (error) {
          toast(error.message, true);
        }
      })
    );
}

function taskCard(task) {
  const due = dueLabel(task);
  const actions = [];
  if (task.status === "created") {
    actions.push(`<button class="primary" data-action="in_progress" data-id="${task.id}">В работу</button>`);
  } else if (task.status === "in_progress") {
    actions.push(`<button class="primary" data-action="done" data-id="${task.id}">Выполнена</button>`);
    actions.push(`<button class="ghost" data-action="created" data-id="${task.id}">В очередь</button>`);
  } else {
    actions.push(`<button class="ghost" data-action="in_progress" data-id="${task.id}">Вернуть в работу</button>`);
  }

  return `
    <article class="task ${task.effective_status}">
      <div class="task-head">
        <div>
          <div class="task-title">${esc(task.title)}</div>
          <div class="task-meta">
            <span class="badge type">${esc(task.promise_type_title || task.promise_type)}</span>
            <span class="badge ${task.effective_status}">${STATUS_LABELS[task.effective_status] || task.effective_status}</span>
            <span class="due ${due.cls}">⏰ ${esc(due.text)}</span>
            <span>оператор ${esc(task.operator_id ?? "—")}</span>
            <button class="ghost" data-call="${esc(task.call_id)}" style="padding:2px 8px;font-size:12.5px">звонок</button>
          </div>
        </div>
        <div class="task-actions">${actions.join("")}</div>
      </div>
      ${task.object ? `<div class="task-meta">Объект: <b>${esc(task.object)}</b></div>` : ""}
      <blockquote class="quote">${esc(task.quote)}</blockquote>
      ${
        (task.actions || []).length > 1
          ? `<ul class="actions-list">${task.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`
          : ""
      }
      <div class="task-meta" style="margin-top:8px">
        <span>срок: ${esc(task.due_hint || task.deadline_source)}</span>
        <span>уверенность ${Math.round((task.confidence || 0) * 100)}%</span>
        <span>${esc(SOURCE_LABELS[task.matched_by] || task.matched_by)}</span>
      </div>
    </article>`;
}

async function loadTasks(append = false) {
  const params = new URLSearchParams();
  if (state.status) params.set("status", state.status);
  if (state.type) params.set("type", state.type);
  if (state.q) params.set("q", state.q);
  params.set("limit", state.limit);
  params.set("offset", state.offset);
  params.set("sort", state.status === "done" ? "-updated_at" : "due_at");

  const token = ++state.loadToken;
  const data = await api(`/api/v1/tasks?${params}`);
  if (token !== state.loadToken) return;

  state.total = data.total;
  const html = data.items.map(taskCard).join("");
  if (append) {
    $("taskList").insertAdjacentHTML("beforeend", html);
  } else {
    $("taskList").innerHTML = html || `<div class="empty">Задач нет. Проверьте фильтры или отправьте звонки на вебхук.</div>`;
  }
  $("loadMoreWrap").classList.toggle("hidden", state.offset + data.items.length >= data.total);

  $("taskList")
    .querySelectorAll("[data-action]")
    .forEach((btn) => btn.addEventListener("click", () => changeStatus(btn.dataset.id, btn.dataset.action, btn)));
  $("taskList")
    .querySelectorAll("[data-call]")
    .forEach((btn) => btn.addEventListener("click", () => openCall(btn.dataset.call)));
}

async function changeStatus(taskId, status, button) {
  button.disabled = true;
  try {
    await api(`/api/v1/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    toast(status === "done" ? "Задача выполнена" : "Статус обновлён");
    await refresh();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

async function openCall(callId) {
  const modal = $("callModal");
  modal.classList.remove("hidden");
  $("callBody").innerHTML = `<div class="empty">Загружаем расшифровку…</div>`;
  try {
    const call = await api(`/api/v1/calls/${callId}`);
    $("callTitle").textContent = `Звонок ${call.id}`;
    const started = call.started_at ? new Date(call.started_at) : null;
    $("callMeta").textContent = [
      call.operator_id != null ? `оператор ${call.operator_id}` : null,
      started ? `начало ${dayFmt(call.started_at)}, ${timeFmt(call.started_at)}` : null,
      `обещаний: ${call.promise_count}`,
    ]
      .filter(Boolean)
      .join(" · ");

    const promiseIndexes = new Set((call.tasks || []).map((t) => t.transcript_index));
    $("callBody").innerHTML = (call.transcript || [])
      .map(
        (r, index) => `
        <div class="replica ${esc(r.speaker)} ${promiseIndexes.has(index) ? "promise" : ""}">
          <div class="who">${r.speaker === "operator" ? "оператор" : "клиент"}</div>
          <div>${esc(r.text)}</div>
        </div>`
      )
      .join("");
  } catch (error) {
    $("callBody").innerHTML = `<div class="empty">${esc(error.message)}</div>`;
  }
}

async function refresh() {
  try {
    const [counts] = await Promise.all([loadCounts(), loadStats()]);
    statusChips(counts);
    await loadTasks(false);
  } catch (error) {
    toast(error.message, true);
  }
}

/* --------------------------------- события -------------------------------- */

$("typeFilter").addEventListener("change", (event) => {
  state.type = event.target.value;
  state.offset = 0;
  refresh();
});

let searchTimer;
$("search").addEventListener("input", (event) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.q = event.target.value.trim();
    state.offset = 0;
    refresh();
  }, 350);
});

$("refresh").addEventListener("click", refresh);
$("loadMore").addEventListener("click", () => {
  state.offset += state.limit;
  loadTasks(true);
});

$("openTypes").addEventListener("click", () => {
  $("typesDrawer").classList.add("open");
  $("typesDrawer").setAttribute("aria-hidden", "false");
});
$("closeTypes").addEventListener("click", () => {
  $("typesDrawer").classList.remove("open");
  $("typesDrawer").setAttribute("aria-hidden", "true");
});
$("closeCall").addEventListener("click", () => $("callModal").classList.add("hidden"));
$("callModal").addEventListener("click", (event) => {
  if (event.target.id === "callModal") $("callModal").classList.add("hidden");
});

$("typeForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    title: $("tTitle").value.trim(),
    description: $("tDescription").value.trim(),
    keywords: $("tKeywords").value.split(",").map((k) => k.trim()).filter(Boolean),
    examples: $("tExamples").value.split("\n").map((e) => e.trim()).filter(Boolean),
  };
  try {
    await api("/api/v1/promise-types", { method: "POST", body: JSON.stringify(payload) });
    toast("Тип добавлен. Новые звонки будут искаться по нему");
    $("typeForm").reset();
    await loadTypes();
  } catch (error) {
    toast(error.message, true);
  }
});

/* ---------------------------------- старт --------------------------------- */

(async function init() {
  await loadHealth();
  await loadTypes();
  await refresh();
  setInterval(loadStats, 30000);
})();
