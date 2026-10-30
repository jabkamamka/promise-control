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
  employee: null,
  onlyMine: false,
};

const STATUS_LABELS = {
  created: "Создана",
  in_progress: "В работе",
  done: "Выполнена",
  overdue: "Просрочена",
  not_fulfilled: "Не выполнена",
};

const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

const SOURCE_LABELS = {
  rule: "правила",
  "custom-rule": "свой тип",
  llm: "ИИ",
};

const ICON = {
  phone: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 3.5h2.9l1.5 4-2 1.5a12.6 12.6 0 0 0 6 6l1.5-2 4 1.5v2.9a2 2 0 0 1-2.2 2A16.6 16.6 0 0 1 4.6 5.7a2 2 0 0 1 2-2.2Z"/></svg>`,
  check: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>`,
  alert: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.5 21 20H3l9-15.5Z"/><path d="M12 10v4.5"/><path d="M12 17.6v.1"/></svg>`,
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
  if (response.status === 401) {
    // Сессия истекла или её нет — уводим на вход, а не показываем «HTTP 401».
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
    throw new Error("Нужно войти в систему");
  }
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

async function loadEmployee() {
  try {
    const data = await api("/auth/me");
    state.employee = data && data.employee ? data.employee : null;
  } catch (error) {
    state.employee = null;
  }
  renderEmployee();
}

/* ------------------------------ уведомления ------------------------------ */

const notif = { items: [], unread: 0, email: null, open: false, known: null };

const EMAIL_LABELS = {
  sent: "письмо отправлено",
  file: "письмо в outbox",
  failed: "письмо не ушло",
  disabled: "без письма",
};

function renderNotifBadge() {
  const badge = $("notifBadge");
  if (!badge) return;
  badge.textContent = notif.unread > 9 ? "9+" : String(notif.unread);
  badge.hidden = notif.unread === 0;
  const button = $("notifBtn");
  if (button) button.classList.toggle("has-unread", notif.unread > 0);
}

function notifTime(value) {
  const date = new Date(value);
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay
    ? new Intl.DateTimeFormat("ru-RU", { timeZone: state.tz, hour: "2-digit", minute: "2-digit" }).format(date)
    : new Intl.DateTimeFormat("ru-RU", { timeZone: state.tz, day: "numeric", month: "short" }).format(date);
}

function renderNotifications() {
  const list = $("notifList");
  if (!list) return;
  const empty = $("notifEmpty");
  const foot = $("notifFoot");

  list.innerHTML = notif.items
    .map(
      (item) => `
      <li class="notif-item ${item.read_at ? "" : "unread"} ${item.kind === "overdue" ? "overdue" : ""}"
          data-notif="${item.id}" data-link="${esc(item.link)}" tabindex="0" role="button">
        <span class="notif-dot" aria-hidden="true"></span>
        <span class="notif-body">
          <span class="notif-title">${esc(item.title)}</span>
          ${item.body ? `<span class="notif-text">${esc(item.body).replace(/\n/g, "<br />")}</span>` : ""}
          <span class="notif-meta">${esc(notifTime(item.created_at))} · ${esc(
            EMAIL_LABELS[item.email_status] || "без письма"
          )}</span>
        </span>
      </li>`
    )
    .join("");

  if (empty) empty.hidden = notif.items.length > 0;
  if (foot) {
    const mode = notif.email ? notif.email.transport : "disabled";
    foot.textContent =
      mode === "smtp"
        ? "Копии писем уходят на рабочую почту."
        : mode === "file"
          ? "Почта не настроена: письма сохраняются в data/outbox."
          : "Отправка писем выключена.";
  }
  renderNotifBadge();
}

async function loadNotifications({ announce = false } = {}) {
  try {
    const data = await api("/api/v1/notifications?limit=20");
    notif.items = data.items || [];
    notif.unread = data.unread || 0;
    notif.email = data.email || null;
    if (announce && notif.known !== null && notif.unread > notif.known) {
      const fresh = notif.unread - notif.known;
      toast(`Новое уведомление: ${fresh}`);
    }
    notif.known = notif.unread;
    renderNotifications();
  } catch (error) {
    /* уведомления не должны ломать панель */
  }
}

function placeNotifPanel() {
  const panel = $("notifPanel");
  const button = $("notifBtn");
  if (!panel || !button) return;
  const rect = button.getBoundingClientRect();
  const width = Math.min(380, window.innerWidth - 24);
  const left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12));
  const height = panel.offsetHeight || 220;
  let top = rect.bottom + 10;
  if (top + height > window.innerHeight - 12) top = rect.top - height - 10;
  top = Math.max(12, Math.min(top, window.innerHeight - height - 12));
  panel.style.width = `${width}px`;
  panel.style.left = `${Math.round(left)}px`;
  panel.style.top = `${Math.round(top)}px`;
}

function toggleNotifPanel(force) {
  const panel = $("notifPanel");
  const button = $("notifBtn");
  if (!panel || !button) return;
  notif.open = typeof force === "boolean" ? force : !notif.open;
  panel.hidden = !notif.open;
  button.setAttribute("aria-expanded", notif.open ? "true" : "false");
  if (notif.open) {
    placeNotifPanel();
    loadNotifications();
  }
}

async function markNotifRead(ids) {
  try {
    const data = await api("/api/v1/notifications/read", {
      method: "POST",
      body: JSON.stringify(ids ? { ids } : {}),
    });
    notif.unread = data.unread;
  } catch (error) {
    /* не мешаем работе */
  }
}

function bindNotifications() {
  const button = $("notifBtn");
  const panel = $("notifPanel");
  if (!button || !panel) return;

  // Панель уносим в body: у карточки фильтров есть backdrop-filter, а он превращает
  // position: fixed во «внутренний» — панель уезжала бы вниз страницы.
  if (panel.parentElement !== document.body) document.body.appendChild(panel);

  button.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleNotifPanel();
  });

  const readAll = $("notifReadAll");
  if (readAll) {
    readAll.addEventListener("click", async (event) => {
      event.stopPropagation();
      await markNotifRead(null);
      notif.items = notif.items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() }));
      renderNotifications();
    });
  }

  const testButton = $("notifTest");
  if (testButton) {
    testButton.addEventListener("click", async (event) => {
      event.stopPropagation();
      const note = $("notifTestNote");
      testButton.disabled = true;
      if (note) note.textContent = "отправляю…";
      try {
        const data = await api("/api/v1/notifications/test", { method: "POST" });
        const where = data.email && data.email.redirect_to ? data.email.redirect_to : data.to;
        if (data.status === "sent") {
          if (note) note.textContent = `доставлено на ${where}`;
          toast(`Письмо отправлено на ${where}`);
        } else if (data.status === "file") {
          if (note) note.textContent = "SMTP не настроен: письмо в data/outbox";
          toast("SMTP не настроен — письмо сохранено в outbox", true);
        } else {
          if (note) note.textContent = data.detail || "не удалось отправить";
          toast(data.detail || "Почта не отправляется", true);
        }
      } catch (error) {
        if (note) note.textContent = error.message;
        toast(error.message, true);
      } finally {
        testButton.disabled = false;
      }
    });
  }

  $("notifList").addEventListener("click", async (event) => {
    const item = event.target.closest("[data-notif]");
    if (!item) return;
    const id = Number(item.dataset.notif);
    await markNotifRead([id]);
    notif.items = notif.items.map((row) =>
      row.id === id ? { ...row, read_at: row.read_at || new Date().toISOString() } : row
    );
    renderNotifications();
    toggleNotifPanel(false);
    if (item.dataset.link) window.location.href = item.dataset.link;
  });

  document.addEventListener("click", (event) => {
    if (!notif.open) return;
    if (event.target.closest("#notifPanel, .notif-wrap")) return;
    toggleNotifPanel(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && notif.open) toggleNotifPanel(false);
  });

  window.addEventListener("resize", () => {
    if (notif.open) placeNotifPanel();
  });

  window.addEventListener("scroll", () => {
    if (notif.open) placeNotifPanel();
  }, { passive: true });
}

function renderEmployee() {
  const box = $("employeeBox");
  if (!box) return;
  if (state.employee) {
    const mine = $("myTasks");
    if (mine) mine.classList.remove("hidden");
    box.innerHTML = `
      <span class="employee-name" title="${esc(state.employee.email)}">${esc(state.employee.full_name)}</span>
      <button class="ghost" id="logoutBtn" type="button">Выйти</button>`;
    const button = $("logoutBtn");
    if (button) {
      button.addEventListener("click", async () => {
        try {
          await api("/auth/logout", { method: "POST" });
        } catch (error) {
          /* всё равно сбрасываем состояние */
        }
        state.employee = null;
        window.location.href = "/login";
      });
    }
  } else {
    const mine = $("myTasks");
    if (mine) {
      mine.classList.add("hidden");
      mine.classList.remove("active");
      mine.setAttribute("aria-pressed", "false");
    }
    state.onlyMine = false;
    // Сайт доступен только после входа: анонимного состояния быть не должно.
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
  }
}

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
      <div class="stat danger"><b>${stats.not_fulfilled ?? 0}</b><span>не выполнено</span></div>
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
  const keys = ["", "overdue", "not_fulfilled", "created", "in_progress", "done"];
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
    { key: "overdue", title: STATUS_LABELS.overdue, count: counts?.overdue, rank: 1 },
    { key: "not_fulfilled", title: STATUS_LABELS.not_fulfilled, count: counts?.not_fulfilled, rank: 2 },
    { key: "in_progress", title: STATUS_LABELS.in_progress, count: counts?.in_progress, rank: 3 },
    { key: "created", title: STATUS_LABELS.created, count: counts?.created, rank: 4 },
    { key: "done", title: STATUS_LABELS.done, count: counts?.done, rank: 5 },
  ];
  $("statusChips").innerHTML = items
    .map((item) => {
      const active = state.status === item.key;
      const label = `${item.title}${item.count != null ? `, задач: ${item.count}` : ""}`;
      return `
      <button type="button" class="chip ${active ? "active" : ""}" data-status="${item.key}" aria-pressed="${active}" aria-label="${esc(label)}">
        <span class="chip-label">${item.title}</span>
        ${item.count != null ? `<span class="count">${item.count}</span>` : ""}
      </button>`;
    })
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
  requestAnimationFrame(placeChipThumb);
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
        <div class="type-item-head">
          <h3>${esc(t.title)}</h3>
          <div class="type-badges">
            <span class="badge ${t.is_builtin ? "created" : "type"}">${t.is_builtin ? "встроенный" : "свой"}</span>
            <span class="badge neutral">${t.tasks_count} задач</span>
          </div>
        </div>
        <p>${esc(t.description || "Без описания")}</p>
        <div class="kw">${(t.keywords || []).map((k) => `<span>${esc(k)}</span>`).join("")}</div>
        ${
          t.is_builtin
            ? ""
            : `<div class="type-actions"><button class="ghost danger-ghost" type="button" data-delete-type="${esc(t.code)}">Удалить тип</button></div>`
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
  const mine = state.employee && task.assignee_id === state.employee.id;
  const busy = task.assignee_id && !mine;

  if (task.status === "created") {
    actions.push(
      busy
        ? `<span class="task-owner-note">взял ${esc(task.assignee_name || "другой сотрудник")}</span>`
        : `<button class="primary" data-action="take" data-id="${task.id}">${
            state.employee ? "Взять в работу" : "Войти и взять"
          }</button>`
    );
  } else if (task.status === "in_progress") {
    actions.push(`<button class="primary" data-action="done" data-id="${task.id}">Выполнена</button>`);
    actions.push(`<button class="ghost" data-action="created" data-id="${task.id}">В очередь</button>`);
  } else {
    actions.push(`<button class="ghost" data-action="in_progress" data-id="${task.id}">Вернуть в работу</button>`);
  }

  return `
    <article class="task ${task.effective_status}" id="task-${esc(task.id)}">
      <div class="task-head">
        <div class="task-main">
          <div class="task-kicker">
            <span class="badge type">${esc(task.promise_type_title || task.promise_type)}</span>
            <span class="badge ${task.effective_status}">${STATUS_LABELS[task.effective_status] || task.effective_status}</span>
            ${task.object ? `<span class="task-object">${esc(task.object)}</span>` : ""}
            ${
              task.assignee_name
                ? `<span class="badge owner ${mine ? "mine" : ""}">${mine ? "взяли вы" : "взял " + esc(task.assignee_name)}</span>`
                : ""
            }
          </div>
          <h3 class="task-title">${esc(task.title)}</h3>
          <div class="task-sub">
            <span class="meta-label">Оператор</span>
            <span>${esc(task.operator_id ?? "—")}</span>
            <span class="task-sub-sep" aria-hidden="true"></span>
            <button class="text-btn" type="button" data-call="${esc(task.call_id)}">${ICON.phone} Исходный звонок</button>
          </div>
        </div>
        <div class="task-side">
          <div class="due-card ${due.cls}">
            <span class="due-label">Срок</span>
            <span class="due ${due.cls}">${esc(due.text)}</span>
          </div>
          <div class="task-actions">${actions.join("")}</div>
        </div>
      </div>
      <blockquote class="quote">${esc(task.quote)}</blockquote>
      ${
        task.verification_status
          ? `<div class="verification ${esc(task.verification_status)}">
              <div class="verification-icon" aria-hidden="true">${
                task.verification_status === "confirmed" ? ICON.check : ICON.alert
              }</div>
              <div class="verification-body">
                <div class="verification-title">${
                  task.verification_status === "confirmed"
                    ? "Клиент подтвердил исполнение"
                    : "Клиент сообщил, что не исполнено"
                }</div>
                ${
                  task.verification_quote
                    ? `<div class="verification-quote">«${esc(task.verification_quote)}»</div>`
                    : ""
                }
                <div class="verification-meta">
                  <span>${
                    task.verified_at ? `проверено ${dayFmt(task.verified_at)}, ${timeFmt(task.verified_at)}` : ""
                  }</span>
                  ${
                    task.verified_call_id
                      ? `<button class="text-btn" type="button" data-call="${esc(task.verified_call_id)}">${ICON.phone} Звонок-проверка</button>`
                      : ""
                  }
                </div>
              </div>
            </div>`
          : ""
      }
      ${
        (task.actions || []).length > 1
          ? `<ul class="actions-list">${task.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`
          : ""
      }
      <div class="task-foot">
        <span class="task-foot-item"><span class="meta-label">Срок из фразы</span> ${esc(task.due_hint || task.deadline_source)}</span>
        <span class="task-foot-item"><span class="meta-label">Уверенность</span> ${Math.round((task.confidence || 0) * 100)}%</span>
        <span class="task-foot-item"><span class="meta-label">Источник</span> ${esc(SOURCE_LABELS[task.matched_by] || task.matched_by)}</span>
      </div>
    </article>`;
}

async function loadTasks(append = false) {
  const params = new URLSearchParams();
  if (state.status) params.set("status", state.status);
  if (state.type) params.set("type", state.type);
  if (state.q) params.set("q", state.q);
  if (state.onlyMine) params.set("assignee_id", "me");
  params.set("limit", state.limit);
  params.set("offset", state.offset);
  params.set("sort", state.status === "done" ? "-updated_at" : "due_at");

  const token = ++state.loadToken;
  const data = await api(`/api/v1/tasks?${params}`);
  if (token !== state.loadToken) return;

  state.total = data.total;
  setQueueCount(data.total);
  const html = data.items.map(taskCard).join("");
  if (append) {
    $("taskList").insertAdjacentHTML("beforeend", html);
  } else {
    $("taskList").innerHTML = html || `<div class="empty"><div class="empty-mark" aria-hidden="true">∅</div><p>Задач нет. Проверьте фильтры или отправьте звонки на вебхук.</p></div>`;
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
  if (!state.employee) {
    window.location.href = "/login?next=/";
    return;
  }
  button.disabled = true;
  try {
    if (status === "take") {
      await api(`/api/v1/tasks/${taskId}/take`, { method: "POST" });
      toast("Задача закреплена за вами");
    } else {
      await api(`/api/v1/tasks/${taskId}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      toast(status === "done" ? "Задача выполнена" : "Статус обновлён");
    }
    await refresh();
  } catch (error) {
    if (String(error.message).includes("войти")) {
      window.location.href = "/login?next=/";
      return;
    }
    toast(error.message, true);
    button.disabled = false;
  }
}

async function openCall(callId) {
  const modal = $("callModal");
  modal.classList.remove("hidden");
  $("callBody").innerHTML = `<div class="empty compact"><div class="empty-mark" aria-hidden="true">…</div><p>Загружаем расшифровку…</p></div>`;
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
    $("callBody").innerHTML = `<div class="empty compact"><div class="empty-mark" aria-hidden="true">!</div><p>${esc(error.message)}</p></div>`;
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

/* ------------------------------ живой интерфейс ---------------------------- */

const numberFmt = new Intl.NumberFormat("ru-RU");
const statPrev = new Map();
let lastSyncAt = 0;

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function setQueueCount(total) {
  const el = $("queueCount");
  if (el && Number.isFinite(Number(total))) el.textContent = numberFmt.format(total);
}

function placeChipThumb() {
  const track = $("statusChips");
  if (!track) return;
  const chip = track.querySelector(".chip.active");
  if (!chip) {
    track.style.setProperty("--thumb-opacity", "0");
    return;
  }
  const trackRect = track.getBoundingClientRect();
  const chipRect = chip.getBoundingClientRect();
  track.style.setProperty("--thumb-x", `${chipRect.left - trackRect.left - track.clientLeft}px`);
  track.style.setProperty("--thumb-y", `${chipRect.top - trackRect.top - track.clientTop}px`);
  track.style.setProperty("--thumb-w", `${chipRect.width}px`);
  track.style.setProperty("--thumb-h", `${chipRect.height}px`);
  track.style.setProperty("--thumb-opacity", "1");
  if (!track.classList.contains("thumb-ready")) {
    requestAnimationFrame(() => track.classList.add("thumb-ready"));
  }
}

function animateStatValue(el, from, to) {
  if (prefersReducedMotion() || from === to) {
    el.textContent = numberFmt.format(to);
    return;
  }
  const start = performance.now();
  const duration = from === 0 ? 760 : 520;
  const tick = (now) => {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = numberFmt.format(Math.round(from + (to - from) * eased));
    if (progress < 1 && el.isConnected) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function animateStats() {
  document.querySelectorAll("#stats .stat").forEach((stat) => {
    const value = stat.querySelector("b");
    const label = stat.querySelector("span")?.textContent?.trim() || "";
    const target = Number(String(value?.textContent || "").replace(/\s/g, ""));
    if (!value || !Number.isFinite(target)) return;
    const from = statPrev.has(label) ? statPrev.get(label) : 0;
    statPrev.set(label, target);
    animateStatValue(value, from, target);
  });
}

function updateSyncAge() {
  const el = $("syncAge");
  if (!el) return;
  if (!lastSyncAt) {
    el.textContent = "синхронизация…";
    return;
  }
  const seconds = Math.max(0, Math.floor((Date.now() - lastSyncAt) / 1000));
  if (seconds < 4) el.textContent = "обновлено только что";
  else if (seconds < 60) el.textContent = `обновлено ${seconds} с назад`;
  else el.textContent = `обновлено ${Math.floor(seconds / 60)} мин назад`;
}

function initLiveUI() {
  const stats = $("stats");
  if (stats) {
    new MutationObserver(() => {
      lastSyncAt = Date.now();
      updateSyncAge();
      animateStats();
    }).observe(stats, { childList: true });
  }

  const chips = $("statusChips");
  if (chips) {
    new ResizeObserver(() => requestAnimationFrame(placeChipThumb)).observe(chips);
  }

  const refreshButton = $("refresh");
  refreshButton?.addEventListener("click", () => {
    refreshButton.classList.remove("is-loading");
    void refreshButton.offsetWidth;
    refreshButton.classList.add("is-loading");
    setTimeout(() => refreshButton.classList.remove("is-loading"), 900);
  });

  document.addEventListener("keydown", (event) => {
    const target = event.target;
    const typing =
      target instanceof HTMLElement &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.tagName === "SELECT" ||
        target.isContentEditable);
    const dialogOpen = !$("callModal").classList.contains("hidden") || $("typesDrawer").classList.contains("open");

    if (event.key === "/" && !typing && !dialogOpen && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      $("search").focus();
      $("search").select();
      return;
    }

    if (event.key === "Escape") {
      if (!$("callModal").classList.contains("hidden")) {
        $("closeCall").click();
        return;
      }
      if ($("typesDrawer").classList.contains("open")) {
        $("closeTypes").click();
        return;
      }
      if (document.activeElement === $("search")) {
        if ($("search").value) {
          $("search").value = "";
          $("search").dispatchEvent(new Event("input", { bubbles: true }));
        }
        $("search").blur();
      }
    }
  });

  setInterval(updateSyncAge, 1000);
}

initLiveUI();

/* ---------------------------------- старт --------------------------------- */

// Переход на страницу аналитики.
const analyticsButton = document.getElementById("openAnalytics");
if (analyticsButton) {
  analyticsButton.addEventListener("click", () => {
    window.location.href = "/analytics";
  });
}

(async function init() {
  await loadHealth();
  await loadEmployee();
  await loadTypes();
  await refresh();
  setInterval(loadStats, 30000);

  bindNotifications();
  await loadNotifications();
  setInterval(() => loadNotifications({ announce: true }), 45000);

  const myTasks = $("myTasks");
  if (myTasks) {
    myTasks.addEventListener("click", () => {
      state.onlyMine = !state.onlyMine;
      myTasks.classList.toggle("active", state.onlyMine);
      myTasks.setAttribute("aria-pressed", state.onlyMine ? "true" : "false");
      state.offset = 0;
      refresh();
    });
  }

  // ссылка из напоминания: /?mine=1 — сразу только свои задачи
  if (new URLSearchParams(window.location.search).get("mine") && state.employee && myTasks) {
    state.onlyMine = true;
    myTasks.classList.add("active");
    myTasks.setAttribute("aria-pressed", "true");
    await refresh();
  }

  // ссылка из письма: /?task=<id> — найти задачу, прокрутить и подсветить
  const focusId = new URLSearchParams(window.location.search).get("task");
  if (focusId) await focusTask(focusId);
})();

async function focusTask(id) {
  let card = document.getElementById(`task-${id}`);

  if (!card && state.employee && !state.onlyMine) {
    state.onlyMine = true;
    const my = $("myTasks");
    if (my) {
      my.classList.add("active");
      my.setAttribute("aria-pressed", "true");
    }
    await refresh();
    card = document.getElementById(`task-${id}`);
  }

  if (!card) {
    try {
      const task = await api(`/api/v1/tasks/${id}`);
      state.q = task.title;
      const search = $("search");
      if (search) search.value = task.title;
      await refresh();
      card = document.getElementById(`task-${id}`);
    } catch (error) {
      /* задача могла быть удалена или недоступна */
    }
  }

  if (card) {
    card.classList.add("focused");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  } else {
    toast("Задача из уведомления не найдена");
  }
}
