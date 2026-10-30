/* ==========================================================================
   Внутренний мессенджер — клиент.
   Ванильный JS без сборки: тот же стиль, что и остальной пульт оператора.
   ========================================================================== */

const API = "";

const state = {
  me: null,
  contacts: [],
  conversations: [],
  totals: { unread: 0, mentions: 0 },
  timezone: "Asia/Yekaterinburg",
  limits: { message_chars: 4000, upload_mb: 10 },
  activeId: null,
  activeConv: null,
  details: null,
  detailsOpen: false,
  messages: [],
  lastId: 0,
  readUpTo: 0,
  typing: [],
  entryLastRead: 0,
  replyTo: null,
  editing: null,
  pendingFile: null,
  pendingMentions: [],
  sending: false,
  atBottom: true,
  pollTimer: null,
  listTimer: null,
  typingSentAt: 0,
  searchTimer: null,
  searchSeq: 0,
  chatSearchTimer: null,
  chatSearchSeq: 0,
  picker: {
    open: false,
    mode: "create",
    kind: "direct",
    channelId: null,
    selected: new Set(),
    query: "",
  },
  mention: { open: false, tokenStart: -1, items: [], active: 0 },
  renaming: false,
};

const $ = (id) => document.getElementById(id);

const ICONS = {
  reply: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7 4 12l5 5"></path><path d="M4 12h9a7 7 0 0 1 7 7"></path></svg>`,
  edit: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l10-10-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path></svg>`,
  trash: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M9 7V4h6v3"></path><path d="m6 7 1 13h10l1-13"></path><path d="M10 11v5"></path><path d="M14 11v5"></path></svg>`,
  check: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"></path></svg>`,
  checks: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m2 12.5 4 4L15 7.5"></path><path d="m9 16.5 9-9"></path></svg>`,
  hash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M9 4 7 20"></path><path d="M17 4l-2 16"></path><path d="M4.5 9h15"></path><path d="M3.5 15h15"></path></svg>`,
  bellOff: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4a5 5 0 0 0-5 5v4l-1.7 3.2h13.4L17 13V9a5 5 0 0 0-5-5Z"></path><path d="M10 19a2 2 0 0 0 4 0"></path><path d="m3 3 18 18"></path></svg>`,
  bell: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4a5 5 0 0 0-5 5v4l-1.7 3.2h13.4L17 13V9a5 5 0 0 0-5-5Z"></path><path d="M10 19a2 2 0 0 0 4 0"></path></svg>`,
  users: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3.2"></circle><path d="M3.5 19c0-3 2.4-5 5.5-5s5.5 2 5.5 5"></path><path d="M16 5.4a3.1 3.1 0 0 1 0 5.9"></path><path d="M17.6 14.4c1.9.6 3.1 2.3 3.1 4.6"></path></svg>`,
  link: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 1 0-5.7-5.7L11.4 7"></path><path d="M14 10a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 1 0 5.7 5.7L12.6 17"></path></svg>`,
  close: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12"></path><path d="M18 6 6 18"></path></svg>`,
  download: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11"></path><path d="m7 11 5 5 5-5"></path><path d="M5 20h14"></path></svg>`,
  image: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="2"></rect><circle cx="9" cy="10" r="1.6"></circle><path d="m4 17 5-5 4 4 3-3 4 4"></path></svg>`,
  pencil: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l10-10-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path></svg>`,
  leave: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H5v16h5"></path><path d="M14 8l4 4-4 4"></path><path d="M9 12h9"></path></svg>`,
  copy: `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"></rect><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"></path></svg>`,
};

/* ------------------------------- помощники -------------------------------- */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function iconSvg(name, className = "icon") {
  const template = document.createElement("template");
  template.innerHTML = String(ICONS[name] || "").trim();
  const svg = template.content.firstElementChild;
  if (svg && className) svg.setAttribute("class", className);
  return svg;
}

function escapeRe(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function toast(message, isError = false) {
  const node = $("toast");
  if (!node) return;
  node.textContent = message;
  node.className = "toast show" + (isError ? " error" : "");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => (node.className = "toast"), 3200);
}

async function api(path, options = {}) {
  const opts = {
    method: options.method || "GET",
    credentials: "same-origin",
    headers: { ...(options.headers || {}) },
  };
  if (options.body !== undefined && options.body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(options.body);
  }
  if (options.raw !== undefined) {
    opts.body = options.raw;
  }
  let response;
  try {
    response = await fetch(API + path, opts);
    setConnection(true);
  } catch (error) {
    setConnection(false);
    throw new Error("Нет связи с сервером");
  }
  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/login?next=${next}`;
    throw new Error("Нужно войти в систему");
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function setConnection(online) {
  const node = $("connectionState");
  const text = $("connectionText");
  if (!node) return;
  node.classList.toggle("offline", !online);
  if (text) text.textContent = online ? "на связи" : "нет связи";
}

/* ----------------------------- формат и время ----------------------------- */

const formatterCache = new Map();

function fmt(options, iso) {
  const key = JSON.stringify(options);
  if (!formatterCache.has(key)) {
    formatterCache.set(
      key,
      new Intl.DateTimeFormat("ru-RU", { timeZone: state.timezone, ...options })
    );
  }
  try {
    return formatterCache.get(key).format(new Date(iso));
  } catch (error) {
    return "";
  }
}

const timeOf = (iso) => fmt({ hour: "2-digit", minute: "2-digit" }, iso);
const dayKey = (iso) =>
  fmt({ year: "numeric", month: "2-digit", day: "2-digit" }, iso).split(".").reverse().join("-");

function todayKey() {
  return dayKey(new Date().toISOString());
}

function dayLabel(iso) {
  const key = dayKey(iso);
  if (key === todayKey()) return "Сегодня";
  const yesterday = new Date(Date.now() - 86400000).toISOString();
  if (key === dayKey(yesterday)) return "Вчера";
  const sameYear = new Date(iso).getFullYear() === new Date().getFullYear();
  return fmt({ day: "numeric", month: "long", ...(sameYear ? {} : { year: "numeric" }) }, iso);
}

function listTime(iso) {
  if (!iso) return "";
  const key = dayKey(iso);
  if (key === todayKey()) return timeOf(iso);
  const yesterday = new Date(Date.now() - 86400000).toISOString();
  if (key === dayKey(yesterday)) return "вчера";
  return fmt(
    { day: "numeric", month: "short", ...(new Date(iso).getFullYear() === new Date().getFullYear() ? {} : { year: "2-digit" }) },
    iso
  );
}

function fullStamp(iso) {
  return fmt({ day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }, iso);
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1).replace(".", ",")} КБ`;
  return `${(value / (1024 * 1024)).toFixed(1).replace(".", ",")} МБ`;
}

function roleLabel(role) {
  return role === "admin" ? "администратор" : "оператор";
}

function plural(count, one, few, many) {
  const value = Math.abs(Number(count) || 0) % 100;
  const tail = value % 10;
  if (value > 10 && value < 20) return many;
  if (tail === 1) return one;
  if (tail >= 2 && tail <= 4) return few;
  return many;
}

function lastSeenLabel(iso) {
  if (!iso) return "не в сети";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 120) return "был(а) только что";
  if (diff < 3600) return `был(а) ${Math.round(diff / 60)} мин назад`;
  if (dayKey(iso) === todayKey()) return `был(а) в ${timeOf(iso)}`;
  return `был(а) ${fmt({ day: "numeric", month: "short" }, iso)}`;
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "??";
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).slice(0, 2).toUpperCase();
}

/* -------------------------------- аватары --------------------------------- */

function avatarEl(person, options = {}) {
  const data = person || {};
  const size = options.size || 36;
  const channel = Boolean(options.channel);
  const node = el("span", "avatar" + (channel ? " channel" : ""));
  node.style.setProperty("--size", `${size}px`);
  node.style.setProperty("--hue", data.hue ?? 220);
  node.setAttribute("aria-hidden", "true");
  if (channel && options.mark === "hash") {
    const mark = el("span", "channel-mark");
    mark.append(iconSvg("hash"));
    node.append(mark);
  } else {
    node.textContent = data.initials || initials(data.full_name || data.title || "");
  }
  if (options.online !== undefined && options.online !== null) {
    node.append(el("span", "presence-dot" + (options.online ? "" : " off")));
  }
  return node;
}

function personFor(id) {
  if (!state.details) return null;
  return (state.details.members || []).find((member) => member.id === id) || null;
}

function mentionName(id) {
  const person = personFor(id);
  if (person) return person.full_name;
  const contact = state.contacts.find((item) => item.id === id);
  return contact ? contact.full_name : "";
}

/* --------------------------------- шапка ---------------------------------- */

function renderMe() {
  const box = $("chatMe");
  if (!box || !state.me) return;
  box.replaceChildren();
  const wrap = el("div", "chat-me-inner");
  wrap.append(avatarEl({ ...state.me, size: 32 }, { size: 32 }));
  const copy = el("div", "chat-me-copy");
  copy.append(el("span", "chat-me-name", state.me.full_name));
  copy.append(el("span", "chat-me-role", roleLabel(state.me.role)));
  wrap.append(copy);
  box.append(wrap);
}

function updateTitle() {
  const unread = state.totals.unread || 0;
  document.title = `${unread ? `(${unread}) ` : ""}Мессенджер — контроль обещаний`;
}

/* -------------------------------- сайдбар --------------------------------- */

function conversationPreview(conv) {
  const last = conv.last_message;
  if (!last) return "Нет сообщений";
  if (last.deleted) return "Сообщение удалено";
  let text = (last.body || "").replace(/\s+/g, " ").trim();
  if (!text) text = "Вложение";
  if (last.sender_id === state.me?.id && last.kind !== "system") text = `Вы: ${text}`;
  return text;
}

function unreadLabel(value) {
  return value > 99 ? "99+" : String(value);
}

function conversationItem(conv) {
  const active = conv.id === state.activeId;
  const button = el(
    "button",
    "conv-item" +
      (active ? " active" : "") +
      (conv.unread ? " has-unread" : "") +
      (conv.muted ? " is-muted" : "")
  );
  button.type = "button";
  button.dataset.id = String(conv.id);
  button.setAttribute("aria-current", active ? "true" : "false");

  const avatarWrap = el("span", "conv-avatar");
  const isChannel = conv.kind === "channel";
  avatarWrap.append(
    avatarEl(
      { ...conv.avatar, full_name: conv.title },
      {
        size: 36,
        channel: conv.kind !== "direct",
        mark: isChannel ? "hash" : null,
        online: conv.kind === "direct" ? Boolean(conv.peer && conv.peer.online) : null,
      }
    )
  );

  const copy = el("span", "conv-copy");
  const titleRow = el("span", "conv-title-row");
  titleRow.append(el("span", "conv-title", conv.title));
  titleRow.append(el("span", "conv-time", listTime(conv.last_message?.created_at || conv.created_at)));
  copy.append(titleRow);
  copy.append(el("span", "conv-preview", conversationPreview(conv)));

  const badges = el("span", "conv-badges");
  if (conv.muted && conv.unread) {
    const mute = el("span", "mute-glyph");
    mute.append(iconSvg("bellOff"));
    mute.title = "Уведомления выключены";
    badges.append(mute);
  }
  if (conv.mentions) badges.append(el("span", "mention-pill", "@"));
  if (conv.unread) badges.append(el("span", "unread-pill", unreadLabel(conv.unread)));

  button.append(avatarWrap, copy, badges);
  button.addEventListener("click", () => openConversation(conv.id));
  return button;
}

function renderSidebar() {
  const list = $("convList");
  if (!list) return;
  const scroll = $("convScroll");
  const scrollTop = scroll ? scroll.scrollTop : 0;
  list.replaceChildren();

  const groups = [
    { kind: "channel", title: "Каналы" },
    { kind: "direct", title: "Личные" },
    { kind: "group", title: "Группы" },
  ];

  for (const group of groups) {
    const items = state.conversations.filter((conv) => conv.kind === group.kind);
    if (!items.length) continue;
    const section = el("section", "conv-section");
    const head = el("div", "conv-section-head");
    head.append(el("span", "", group.title));
    head.append(el("b", "", String(items.length)));
    section.append(head);
    items.forEach((conv) => section.append(conversationItem(conv)));
    list.append(section);
  }

  if (!state.conversations.length) {
    list.append(
      el(
        "p",
        "sidebar-empty",
        "Пока нет диалогов. Нажмите «Новый чат», чтобы написать коллеге."
      )
    );
  }

  const count = state.conversations.length;
  const counter = $("sidebarCount");
  if (counter) {
    counter.textContent = count
      ? `${count} ${plural(count, "диалог", "диалога", "диалогов")}`
      : "Диалоги";
  }

  if (scroll) scroll.scrollTop = scrollTop;
}

function renderTotals() {
  const node = $("sidebarTotals");
  if (!node) return;
  const { unread, mentions } = state.totals;
  if (!unread && !mentions) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  const parts = [];
  if (unread) parts.push(`непрочитанных: ${unread}`);
  if (mentions) parts.push(`упоминаний: ${mentions}`);
  node.textContent = parts.join(" · ");
  node.hidden = false;
}

function renderEmptyChannels() {
  const box = $("emptyChannels");
  if (!box) return;
  box.replaceChildren();
  state.conversations
    .filter((conv) => conv.kind === "channel")
    .slice(0, 4)
    .forEach((conv) => {
      const button = el("button", "empty-channel");
      button.type = "button";
      button.append(el("span", "", "#"));
      button.append(document.createTextNode(conv.title));
      if (conv.unread) button.append(el("span", "", String(conv.unread)));
      button.addEventListener("click", () => openConversation(conv.id));
      box.append(button);
    });
}

/* -------------------------------- диалоги --------------------------------- */

function updateHead() {
  const conv = state.activeConv;
  if (!conv) return;
  $("chatTitle").textContent = conv.title;

  const subtitle = $("chatSubtitle");
  subtitle.replaceChildren();
  if (conv.kind === "direct") {
    const online = Boolean(conv.peer && conv.peer.online);
    const span = el("span", online ? "online" : "", online ? "в сети" : "не в сети");
    subtitle.append(span);
  } else if (conv.kind === "group") {
    subtitle.append(
      document.createTextNode(
        `${conv.member_count} ${plural(conv.member_count, "участник", "участника", "участников")}${
          conv.online_count ? ` · ${conv.online_count} в сети` : ""
        }`
      )
    );
  } else {
    subtitle.append(document.createTextNode(conv.topic || "общий канал"));
  }

  const avatarBox = $("headAvatar");
  avatarBox.replaceChildren(
    avatarEl(
      { ...conv.avatar, full_name: conv.title },
      {
        size: 40,
        channel: conv.kind !== "direct",
        mark: conv.kind === "channel" ? "hash" : null,
        online: conv.kind === "direct" ? Boolean(conv.peer && conv.peer.online) : null,
      }
    )
  );

  const detailsButton = $("toggleDetails");
  detailsButton.classList.toggle("active", state.detailsOpen);
  detailsButton.setAttribute("aria-expanded", String(state.detailsOpen));
}

function showWorkspace() {
  $("chatEmpty").classList.add("hidden");
  $("chatWorkspace").classList.remove("hidden");
  $("messenger").classList.add("chat-open");
}

function showEmpty() {
  $("chatWorkspace").classList.add("hidden");
  $("chatEmpty").classList.remove("hidden");
  $("messenger").classList.remove("chat-open");
}

function clearComposerModes() {
  state.replyTo = null;
  state.editing = null;
  state.pendingFile = null;
  state.pendingMentions = [];
  const input = $("composerInput");
  if (input) {
    input.value = "";
    resizeInput();
  }
  const fileInput = $("fileInput");
  if (fileInput) fileInput.value = "";
  renderComposerState();
}

function closeConversation() {
  state.activeId = null;
  state.activeConv = null;
  state.details = null;
  state.messages = [];
  state.lastId = 0;
  state.readUpTo = 0;
  state.typing = [];
  state.detailsOpen = false;
  state.renaming = false;
  clearComposerModes();
  $("messages").replaceChildren();
  $("details").hidden = true;
  $("messenger").classList.remove("with-details");
  const toggle = $("toggleDetails");
  if (toggle) toggle.setAttribute("aria-expanded", "false");
  closeChatMenu();
  closeChatSearch();
  renderTyping();
  showEmpty();
  renderSidebar();
  history.replaceState(null, "", "/chat");
}

async function openConversation(channelId, options = {}) {
  const id = Number(channelId);
  if (!id) return;
  if (state.activeId === id && !options.aroundId) {
    if (window.matchMedia("(max-width: 960px)").matches) showWorkspace();
    markReadIfVisible();
    return;
  }

  clearConvSearch();
  closeChatMenu();
  closeChatSearch();
  clearComposerModes();

  state.activeId = id;
  state.activeConv = state.conversations.find((conv) => conv.id === id) || null;
  state.messages = [];
  state.lastId = 0;
  state.readUpTo = 0;
  state.typing = [];
  state.entryLastRead = 0;
  state.atBottom = true;

  showWorkspace();
  renderSidebar();
  if (state.activeConv) updateHead();
  else $("chatTitle").textContent = "Диалог";
  $("messages").replaceChildren();
  setMessagesLoading(true);
  $("jumpLatest").classList.add("hidden");

  try {
    const around = Number(options.aroundId) || 0;
    const [details, data] = await Promise.all([
      api(`/chat/conversations/${id}`),
      api(
        `/chat/conversations/${id}/messages?` +
          (around ? `around_id=${around}&limit=60` : "limit=50")
      ),
    ]);
    if (state.activeId !== id) return;
    state.details = details;
    state.activeConv = details.conversation;
    state.entryLastRead = details.conversation.last_read_id || 0;
    state.messages = data.messages || [];
    state.readUpTo = data.read_up_to || 0;
    state.typing = data.typing || [];
    state.lastId = state.messages.length ? state.messages[state.messages.length - 1].id : 0;

    setMessagesLoading(false);
    updateHead();
    renderMessages({ initial: true });
    renderTyping();
    if (state.detailsOpen) renderDetails();

    if (around) {
      requestAnimationFrame(() => scrollToMessage(around, { flash: true }));
    } else {
      requestAnimationFrame(() => scrollToBottom(false));
    }
    if (options.push !== false) {
      history.replaceState(null, "", `/chat?conv=${id}`);
    }
    markReadIfVisible();
    if (!window.matchMedia("(max-width: 960px)").matches) {
      $("composerInput").focus({ preventScroll: true });
    }
  } catch (error) {
    setMessagesLoading(false);
    if (error.status === 403 || error.status === 404) {
      toast(error.message, true);
      state.conversations = state.conversations.filter((conv) => conv.id !== id);
      closeConversation();
      return;
    }
    const box = el("div", "chat-error", error.message || "Не удалось открыть диалог");
    $("messages").append(box);
  }
}

/* ------------------------------- сообщения -------------------------------- */

function setMessagesLoading(loading) {
  $("messagesLoader").classList.toggle("hidden", !loading);
}

function renderMessages(options = {}) {
  const container = $("messages");
  const scroll = $("messageScroll");
  const previousTop = scroll.scrollTop;
  container.replaceChildren();

  if (!state.messages.length) {
    container.classList.add("is-empty");
    container.append(
      el(
        "p",
        "messages-empty",
        "Пока тихо. Напишите первым — сообщение появится у всех участников."
      )
    );
    return;
  }
  container.classList.remove("is-empty");

  const fragment = document.createDocumentFragment();
  let previous = null;
  let unreadShown = !options.initial || !state.entryLastRead;

  state.messages.forEach((msg) => {
    if (!previous || dayKey(previous.created_at) !== dayKey(msg.created_at)) {
      fragment.append(dayDivider(msg.created_at));
    }
    if (!unreadShown && isIncomingUnread(msg)) {
      fragment.append(unreadDivider());
      unreadShown = true;
    }
    const compact =
      Boolean(previous) &&
      previous.sender?.id === msg.sender?.id &&
      previous.kind !== "system" &&
      msg.kind !== "system" &&
      dayKey(previous.created_at) === dayKey(msg.created_at) &&
      new Date(msg.created_at) - new Date(previous.created_at) < 5 * 60000;
    fragment.append(messageNode(msg, { compact }));
    previous = msg;
  });

  container.append(fragment);
  updateStatuses();
  if (options.initial && !options.aroundId) {
    requestAnimationFrame(() => scrollToBottom(false));
  } else if (options.preserveScroll) {
    scroll.scrollTop = previousTop;
  }
}

function dayDivider(iso) {
  const node = el("div", "day-divider");
  node.append(el("span", "", dayLabel(iso)));
  return node;
}

function isIncomingUnread(message) {
  return Boolean(
    state.entryLastRead &&
      message.id > state.entryLastRead &&
      message.kind !== "system" &&
      message.sender &&
      message.sender.id !== state.me?.id
  );
}

function unreadDivider() {
  const node = el("div", "unread-divider");
  node.append(el("span", "", "Новые сообщения"));
  return node;
}

function messageNode(msg, options = {}) {
  const own = Boolean(msg.sender && state.me && msg.sender.id === state.me.id);
  const compact = Boolean(options.compact);
  const isSystem = msg.kind === "system";

  if (isSystem) {
    const row = el("div", "msg system");
    row.dataset.messageId = String(msg.id);
    row.append(el("span", "system-pill", msg.body));
    return row;
  }

  const row = el(
    "div",
    "msg" + (own ? " own" : "") + (compact ? " compact" : "") + (msg.deleted ? " deleted" : "")
  );
  row.dataset.messageId = String(msg.id);
  row.dataset.own = own ? "1" : "0";

  const avatarWrap = el("div", "msg-avatar");
  if (!compact) {
    avatarWrap.append(
      avatarEl(msg.sender || { full_name: "Сотрудник", initials: "??", hue: 220 }, { size: 29 })
    );
  }
  const content = el("div", "msg-content");

  if (!compact && !own && msg.sender) {
    const name = el("span", "msg-name", msg.sender.full_name);
    name.style.color = `hsl(${msg.sender.hue ?? 220} 45% 32%)`;
    content.append(name);
  }

  const bubble = el("div", "msg-bubble");

  if (msg.reply_to) {
    const quote = el("button", "msg-reply");
    quote.type = "button";
    quote.dataset.target = String(msg.reply_to.id);
    quote.append(el("b", "", msg.reply_to.sender_name || "Сотрудник"));
    quote.append(
      el("span", "", msg.reply_to.deleted ? "Сообщение удалено" : msg.reply_to.body || "Вложение")
    );
    quote.addEventListener("click", () => scrollToMessage(msg.reply_to.id, { flash: true }));
    bubble.append(quote);
  }

  if (msg.attachment) {
    bubble.append(attachmentNode(msg.attachment, msg));
  }

  if (msg.body) {
    const text = el("div", "msg-text");
    renderRichText(text, msg.body, msg.mentions);
    bubble.append(text);
  } else if (msg.deleted) {
    bubble.append(el("div", "msg-text", "Сообщение удалено"));
  }

  const meta = el("div", "msg-meta");
  const time = el("time", "", timeOf(msg.created_at));
  time.setAttribute("datetime", msg.created_at);
  time.setAttribute("title", fullStamp(msg.created_at));
  meta.append(time);
  if (msg.edited_at && !msg.deleted) meta.append(el("span", "", "изменено"));
  bubble.append(meta);

  const tools = el("div", "msg-tools");
  if (!msg.deleted) {
    const replyButton = toolButton("reply", "Ответить", () => startReply(msg));
    tools.append(replyButton);
    if (own && msg.body) {
      tools.append(toolButton("edit", "Изменить", () => startEdit(msg)));
    }
    const canDelete = own || state.details?.can_manage || state.me?.role === "admin";
    if (canDelete) {
      const button = toolButton("trash", "Удалить", () => deleteMessage(msg));
      button.classList.add("danger");
      tools.append(button);
    }
  }
  if (tools.childElementCount) bubble.append(tools);
  else tools.remove();

  content.append(bubble);
  row.append(avatarWrap, content);

  const target = bubble.querySelector(".msg-reply");
  if (target) target.dataset.target = String(msg.reply_to.id);
  return row;
}

function toolButton(iconName, label, handler) {
  const button = el("button");
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(iconSvg(iconName));
  button.addEventListener("click", handler);
  return button;
}

function attachmentNode(attachment, msg) {
  if (attachment.is_image) {
    const link = el("a", "msg-image");
    link.href = attachment.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = attachment.filename;
    const image = document.createElement("img");
    image.src = attachment.url;
    image.alt = attachment.filename;
    image.loading = "lazy";
    link.append(image);
    return link;
  }

  const link = el("a", "file-card");
  link.href = attachment.url;
  link.download = attachment.filename;
  const extension = (attachment.filename.split(".").pop() || "файл").slice(0, 4);
  link.append(el("span", "file-glyph", extension));
  const copy = el("span", "file-copy");
  copy.append(el("b", "", attachment.filename));
  copy.append(el("small", "", formatBytes(attachment.size)));
  link.append(copy);
  const download = iconSvg("download");
  link.append(download);
  link.title = `Скачать ${attachment.filename}`;
  return link;
}

function renderRichText(container, text, mentionIds) {
  const ids = Array.isArray(mentionIds) ? mentionIds : [];
  const names = ids
    .map((id) => mentionName(id))
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  const mentionPart = names.length
    ? `|@(?:${names.map(escapeRe).join("|")})`
    : "";
  const pattern = new RegExp(`(https?:\\/\\/[^\\s]+${mentionPart})`, "gi");
  const parts = String(text).split(pattern);

  parts.forEach((part) => {
    if (!part) return;
    const urlMatch = part.match(/^(https?:\/\/[^\s]+?)([.,;:!?)]*)$/);
    if (urlMatch) {
      const link = el("a", "", urlMatch[1]);
      link.href = urlMatch[1];
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      container.append(link);
      if (urlMatch[2]) container.append(document.createTextNode(urlMatch[2]));
      return;
    }
    if (part[0] === "@" && names.some((name) => part.toLowerCase() === "@" + name.toLowerCase())) {
      container.append(el("span", "mention", part));
      return;
    }
    container.append(document.createTextNode(part));
  });
}

function updateStatuses() {
  const container = $("messages");
  container.querySelectorAll(".msg-status").forEach((node) => node.remove());
  if (!state.details || state.details.conversation.kind !== "direct") return;
  const own = Array.from(container.querySelectorAll('.msg.own[data-message-id]')).filter(
    (node) => node.querySelector(".msg-meta")
  );
  if (!own.length) return;
  const last = own[own.length - 1];
  const id = Number(last.dataset.messageId);
  const seen = id <= state.readUpTo;
  const status = el("span", "msg-status");
  status.append(iconSvg(seen ? "checks" : "check"));
  status.append(document.createTextNode(seen ? "прочитано" : "отправлено"));
  last.querySelector(".msg-meta").append(status);
}

function appendMessages(messages) {
  const fresh = (messages || []).filter(
    (msg) => msg.id > state.lastId && !state.messages.some((item) => item.id === msg.id)
  );
  if (!fresh.length) return;
  const container = $("messages");
  const previous = state.messages[state.messages.length - 1] || null;
  const nearBottom = isNearBottom();
  const fragment = document.createDocumentFragment();
  let cursor = previous;

  fresh.forEach((msg) => {
    if (!cursor || dayKey(cursor.created_at) !== dayKey(msg.created_at)) {
      fragment.append(dayDivider(msg.created_at));
    }
    const compact =
      Boolean(cursor) &&
      cursor.kind !== "system" &&
      msg.kind !== "system" &&
      cursor.sender?.id === msg.sender?.id &&
      dayKey(cursor.created_at) === dayKey(msg.created_at) &&
      new Date(msg.created_at) - new Date(cursor.created_at) < 5 * 60000;
    const node = messageNode(msg, { compact });
    node.classList.add("fresh");
    fragment.append(node);
    cursor = msg;
    state.messages.push(msg);
    state.lastId = Math.max(state.lastId, msg.id);
  });

  const empty = container.querySelector(".messages-empty");
  if (empty) empty.remove();
  container.classList.remove("is-empty");
  container.append(fragment);
  updateStatuses();

  if (nearBottom && document.visibilityState === "visible") {
    scrollToBottom(true);
    $("jumpLatest").classList.add("hidden");
  } else {
    $("jumpLatest").classList.remove("hidden");
  }
  markReadIfVisible();
}

function isNearBottom() {
  const scroll = $("messageScroll");
  if (!scroll) return true;
  return scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 90;
}

function scrollToBottom(smooth = false) {
  const scroll = $("messageScroll");
  if (!scroll) return;
  scroll.scrollTo({ top: scroll.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  state.atBottom = true;
  $("jumpLatest").classList.add("hidden");
}

function scrollToMessage(messageId, options = {}) {
  const id = Number(messageId);
  const node = $("messages").querySelector(`[data-message-id="${id}"]`);
  if (!node) {
    if (state.activeId) openConversation(state.activeId, { aroundId: id });
    return;
  }
  node.scrollIntoView({ block: "center", behavior: "smooth" });
  const bubble = node.querySelector(".msg-bubble") || node;
  if (options.flash !== false) {
    bubble.classList.add("flash");
    setTimeout(() => bubble.classList.remove("flash"), 1200);
  }
  closeChatSearch();
}

/* -------------------------------- действия -------------------------------- */

function startReply(message) {
  if (!message || message.deleted) return;
  state.editing = null;
  state.replyTo = message;
  renderComposerState();
  $("composerInput").focus({ preventScroll: true });
}

function startEdit(message) {
  if (!message || message.deleted) return;
  state.replyTo = null;
  state.pendingFile = null;
  $("fileInput").value = "";
  state.editing = message;
  const input = $("composerInput");
  input.value = message.body || "";
  resizeInput();
  renderComposerState();
  input.focus({ preventScroll: true });
  input.setSelectionRange(input.value.length, input.value.length);
}

function renderComposerState() {
  const banner = $("replyBanner");
  const attachment = $("attachmentChip");
  const composer = $("composer");
  const cancel = $("cancelEdit");
  const hint = $("composerHint");

  banner.replaceChildren();
  if (state.replyTo) {
    banner.classList.remove("hidden");
    const copy = el("div", "banner-copy");
    copy.append(el("b", "", `Ответ · ${state.replyTo.sender?.full_name || "Сотрудник"}`));
    copy.append(el("span", "", state.replyTo.body || "Вложение"));
    banner.append(copy);
    const close = el("button", "text-btn", "Отмена");
    close.type = "button";
    close.addEventListener("click", () => {
      state.replyTo = null;
      renderComposerState();
    });
    banner.append(close);
  } else {
    banner.classList.add("hidden");
  }

  attachment.replaceChildren();
  if (state.pendingFile) {
    attachment.classList.remove("hidden");
    const file = state.pendingFile;
    if (file.type && file.type.startsWith("image/")) {
      const image = document.createElement("img");
      image.src = URL.createObjectURL(file);
      image.alt = "";
      attachment.append(image);
    } else {
      const extension = (file.name.split(".").pop() || "файл").slice(0, 4);
      attachment.append(el("span", "file-glyph", extension));
    }
    const copy = el("span", "attach-copy");
    copy.append(el("b", "", file.name));
    copy.append(el("small", "", `${formatBytes(file.size)} · готов к отправке`));
    attachment.append(copy);
    const remove = el("button", "text-btn", "Убрать");
    remove.type = "button";
    remove.addEventListener("click", () => {
      state.pendingFile = null;
      $("fileInput").value = "";
      renderComposerState();
    });
    attachment.append(remove);
  } else {
    attachment.classList.add("hidden");
  }

  composer.classList.toggle("editing", Boolean(state.editing));
  cancel.classList.toggle("hidden", !state.editing);
  hint.textContent = state.editing
    ? "Правка сообщения · Enter — сохранить · Esc — отменить"
    : "Enter — отправить · Shift + Enter — новая строка";
  updateComposerLimit();
}

async function deleteMessage(message) {
  if (!message || message.deleted) return;
  if (!window.confirm("Удалить сообщение? Оно исчезнет у всех участников.")) return;
  try {
    await api(`/chat/messages/${message.id}`, { method: "DELETE" });
    message.deleted = true;
    message.body = "";
    if (message.attachment) message.attachment = null;
    renderMessages({ preserveScroll: true });
    refreshConversations().catch(() => {});
    toast("Сообщение удалено");
  } catch (error) {
    toast(error.message, true);
  }
}

function resizeInput() {
  const input = $("composerInput");
  if (!input) return;
  input.style.height = "auto";
  const next = Math.min(input.scrollHeight, 148);
  input.style.height = `${Math.max(next, 38)}px`;
}

function updateComposerLimit() {
  const input = $("composerInput");
  const node = $("composerLimit");
  if (!input || !node) return;
  const max = state.limits.message_chars || 4000;
  const length = input.value.length;
  if (length > max * 0.8) {
    node.textContent = `${length} / ${max}`;
    node.classList.toggle("warn", length >= max - 50);
  } else {
    node.textContent = "";
    node.classList.remove("warn");
  }
}

function filteredMentionToken() {
  const input = $("composerInput");
  const before = input.value.slice(0, input.selectionStart);
  const match = before.match(/(^|\s)@([\p{L}\p{N}._-]*)$/u);
  if (!match) return null;
  return {
    query: match[2],
    start: before.length - match[2].length - 1,
  };
}

function openMentionPop() {
  const token = filteredMentionToken();
  if (!token || !state.details) {
    closeMentionPop();
    return;
  }
  const members = state.details.members || [];
  const items = members
    .filter((member) => member.id !== state.me?.id)
    .filter((member) => {
      const query = token.query.toLowerCase();
      return !query || member.full_name.toLowerCase().includes(query);
    })
    .slice(0, 8);
  if (!items.length) {
    closeMentionPop();
    return;
  }
  state.mention = { open: true, tokenStart: token.start, items, active: 0 };
  renderMentionPop();
}

function renderMentionPop() {
  const pop = $("mentionPop");
  if (!pop) return;
  if (!state.mention.open) {
    pop.classList.add("hidden");
    return;
  }
  pop.replaceChildren();
  state.mention.items.forEach((person, index) => {
    const button = el(
      "button",
      "mention-option" + (index === state.mention.active ? " active" : "")
    );
    button.type = "button";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(index === state.mention.active));
    button.append(avatarEl(person, { size: 24 }));
    button.append(el("b", "", person.full_name));
    button.append(el("small", "", person.online ? "в сети" : "не в сети"));
    button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      insertMention(person);
    });
    pop.append(button);
  });
  pop.classList.remove("hidden");
}

function closeMentionPop() {
  state.mention.open = false;
  $("mentionPop")?.classList.add("hidden");
}

function insertMention(person) {
  const input = $("composerInput");
  const token = state.mention.tokenStart;
  const caret = input.selectionStart;
  const before = input.value.slice(0, token);
  const after = input.value.slice(caret);
  const text = `@${person.full_name} `;
  input.value = before + text + after;
  const position = before.length + text.length;
  input.setSelectionRange(position, position);
  if (!state.pendingMentions.includes(person.id)) state.pendingMentions.push(person.id);
  closeMentionPop();
  resizeInput();
  updateComposerLimit();
  input.focus();
}

function detectedMentions(text) {
  const ids = new Set();
  const lower = String(text || "").toLowerCase();
  (state.details?.members || []).forEach((member) => {
    if (member.id === state.me?.id) return;
    if (lower.includes(`@${member.full_name.toLowerCase()}`)) ids.add(member.id);
  });
  state.pendingMentions.forEach((id) => {
    const name = mentionName(id);
    if (name && lower.includes(`@${name.toLowerCase()}`)) ids.add(id);
  });
  return Array.from(ids);
}

function activeMentionsFor(text) {
  return detectedMentions(text);
}

/* -------------------------------- отправка -------------------------------- */

async function submitComposer(event) {
  event.preventDefault();
  if (state.sending || !state.activeId) return;
  if (state.mention.open) return;
  const input = $("composerInput");
  const text = input.value.trim();
  const channel = state.activeId;

  if (state.editing) {
    if (!text) {
      toast("Пустое сообщение сохранить нельзя", true);
      return;
    }
    await saveEdit(text, channel);
    return;
  }

  if (!text && !state.pendingFile) return;

  if (state.pendingFile) {
    await sendAttachment(text, channel);
    return;
  }

  await sendText(text, channel);
}

async function sendText(text, channel) {
  const temp = {
    replyTo: state.replyTo,
    mentions: activeMentionsFor(text),
  };
  setSending(true);
  try {
    const data = await api(`/chat/conversations/${channel}/messages`, {
      method: "POST",
      body: {
        body: text,
        reply_to: temp.replyTo ? temp.replyTo.id : null,
        mentions: temp.mentions,
      },
    });
    if (state.activeId === channel) {
      appendMessages([data.message]);
      state.lastId = Math.max(state.lastId, data.message.id);
      resetComposer();
      scrollToBottom(true);
      markReadIfVisible();
      refreshConversations().catch(() => {});
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    setSending(false);
  }
}

async function saveEdit(text, channel) {
  const message = state.editing;
  if (!message) return;
  setSending(true);
  try {
    const data = await api(`/chat/messages/${message.id}`, {
      method: "PATCH",
      body: { body: text },
    });
    if (state.activeId === channel) {
      const index = state.messages.findIndex((item) => item.id === message.id);
      if (index >= 0) state.messages[index] = data.message;
      resetComposer();
      renderMessages({ preserveScroll: true });
      refreshConversations().catch(() => {});
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    setSending(false);
  }
}

async function sendAttachment(caption, channel) {
  const file = state.pendingFile;
  if (!file) return;
  setSending(true);
  const params = new URLSearchParams({
    filename: file.name,
    caption,
  });
  if (state.replyTo) params.set("reply_to", String(state.replyTo.id));
  try {
    const response = await fetch(
      `${API}/chat/conversations/${channel}/attachments?${params.toString()}`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      }
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    if (state.activeId === channel) {
      appendMessages([data.message]);
      state.lastId = Math.max(state.lastId, data.message.id);
      resetComposer();
      scrollToBottom(true);
      markReadIfVisible();
      refreshConversations().catch(() => {});
    }
  } catch (error) {
    if (error.status === 401) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
      return;
    }
    toast(error.message || "Не удалось отправить файл", true);
  } finally {
    setSending(false);
  }
}

function setSending(value) {
  state.sending = value;
  const button = $("sendBtn");
  if (button) button.disabled = value;
  const hint = $("composerHint");
  if (hint && value) hint.textContent = "Отправляем…";
  else if (hint) renderComposerState();
}

function resetComposer() {
  state.replyTo = null;
  state.editing = null;
  state.pendingFile = null;
  state.pendingMentions = [];
  const input = $("composerInput");
  input.value = "";
  $("fileInput").value = "";
  resizeInput();
  renderComposerState();
  input.focus({ preventScroll: true });
}

/* ------------------------------- прочтение -------------------------------- */

function markReadIfVisible() {
  if (!state.activeId || !state.lastId) return;
  if (document.visibilityState !== "visible") return;
  const conv = state.activeConv;
  if (conv && state.lastId <= (conv.last_read_id || 0)) return;
  const channel = state.activeId;
  const last = state.lastId;
  api(`/chat/conversations/${channel}/read`, {
    method: "POST",
    body: { message_id: last },
  })
    .then(() => {
      if (state.activeId !== channel) return;
      if (state.activeConv) state.activeConv.last_read_id = last;
      const item = state.conversations.find((entry) => entry.id === channel);
      if (item) {
        item.last_read_id = last;
        if (item.unread || item.mentions) {
          item.unread = 0;
          item.mentions = 0;
          renderSidebar();
          refreshTotalsFromState();
        }
      }
    })
    .catch(() => {});
}

function refreshTotalsFromState() {
  const unread = state.conversations
    .filter((conv) => !conv.muted)
    .reduce((sum, conv) => sum + (conv.unread || 0), 0);
  const mentions = state.conversations
    .filter((conv) => !conv.muted)
    .reduce((sum, conv) => sum + (conv.mentions || 0), 0);
  state.totals = { unread, mentions };
  renderTotals();
  updateTitle();
}

/* -------------------------------- опрос ----------------------------------- */

function scheduleMessagePoll(delay = 2200) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(pollMessages, delay);
}

async function pollMessages() {
  try {
    if (state.activeId && document.visibilityState === "visible") {
      const channel = state.activeId;
      const data = await api(
        `/chat/conversations/${channel}/messages?after_id=${state.lastId}&limit=100`
      );
      if (state.activeId !== channel) return;
      state.readUpTo = data.read_up_to || 0;
      state.typing = data.typing || [];
      renderTyping();
      updateStatuses();
      if (data.messages && data.messages.length) {
        appendMessages(data.messages);
      }
      markReadIfVisible();
    }
  } catch (error) {
    if (error.status === 403 || error.status === 404) {
      toast("Диалог больше недоступен", true);
      closeConversation();
      refreshConversations().catch(() => {});
    }
  } finally {
    scheduleMessagePoll();
  }
}

function scheduleListPoll(delay = 8000) {
  clearTimeout(state.listTimer);
  state.listTimer = setTimeout(async () => {
    try {
      await refreshConversations();
    } catch (error) {
      /* связь покажем по индикатору */
    } finally {
      scheduleListPoll();
    }
  }, delay);
}

async function refreshConversations() {
  if (document.visibilityState !== "visible") return;
  const data = await api("/chat/bootstrap");
  const previousMentions = state.totals.mentions || 0;
  state.me = data.me;
  state.contacts = data.contacts || [];
  state.conversations = data.conversations || [];
  state.totals = data.totals || { unread: 0, mentions: 0 };
  state.timezone = data.timezone || state.timezone;
  state.limits = data.limits || state.limits;
  renderMe();
  renderSidebar();
  renderTotals();
  renderEmptyChannels();
  updateTitle();

  if (state.activeId) {
    const conv = state.conversations.find((item) => item.id === state.activeId);
    if (!conv) {
      closeConversation();
    } else {
      state.activeConv = conv;
      updateHead();
      if (!state.details) {
        loadDetails().catch(() => {});
      }
    }
  }

  if (data.totals && data.totals.mentions > previousMentions) {
    toast("Вас упомянули в рабочей переписке");
  }
}

async function loadDetails() {
  if (!state.activeId) return;
  const details = await api(`/chat/conversations/${state.activeId}`);
  state.details = details;
  state.activeConv = details.conversation;
  updateHead();
  if (state.detailsOpen) renderDetails();
}

function renderTyping() {
  const node = $("typingLine");
  if (!node) return;
  node.replaceChildren();
  const names = (state.typing || []).filter(Boolean);
  if (!names.length) return;
  let text;
  if (names.length === 1) text = `${names[0]} печатает`;
  else if (names.length === 2) text = `${names[0]} и ${names[1]} печатают`;
  else text = "Несколько человек печатают";
  node.append(document.createTextNode(text));
  const dots = el("span", "dots");
  dots.append(el("i"), el("i"), el("i"));
  node.append(dots);
}

/* ------------------------------- участники -------------------------------- */

function toggleDetails() {
  if (!state.activeId) return;
  state.detailsOpen = !state.detailsOpen;
  const panel = $("details");
  panel.hidden = !state.detailsOpen;
  $("messenger").classList.toggle("with-details", state.detailsOpen);
  const button = $("toggleDetails");
  button.classList.toggle("active", state.detailsOpen);
  button.setAttribute("aria-expanded", String(state.detailsOpen));
  if (state.detailsOpen) {
    if (state.details) renderDetails();
    else loadDetails().catch((error) => toast(error.message, true));
  }
}

function renderDetails() {
  const panel = $("details");
  if (!panel || !state.details) return;
  const { conversation, members } = state.details;
  panel.replaceChildren();

  const head = el("div", "details-head");
  const close = el("button", "icon-btn details-close");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть панель участников");
  close.append(iconSvg("close"));
  close.addEventListener("click", toggleDetails);
  head.append(close);

  const avatarBox = el("div", "details-avatar");
  avatarBox.append(
    avatarEl(
      { ...conversation.avatar, full_name: conversation.title },
      {
        size: 58,
        channel: conversation.kind !== "direct",
        mark: conversation.kind === "channel" ? "hash" : null,
      }
    )
  );
  head.append(avatarBox);
  head.append(el("h3", "details-title", conversation.title));

  const sub = el("p", "details-sub");
  if (conversation.kind === "direct") {
    const peer = conversation.peer;
    sub.textContent = peer ? (peer.online ? "в сети" : lastSeenLabel(peer.last_seen_at)) : "личный диалог";
  } else if (conversation.kind === "channel") {
    sub.textContent = `канал · ${members.length} ${plural(members.length, "участник", "участника", "участников")}`;
  } else {
    sub.textContent = `группа · ${members.length} ${plural(members.length, "участник", "участника", "участников")}`;
  }
  head.append(sub);
  if (conversation.topic) head.append(el("p", "details-topic", conversation.topic));
  panel.append(head);

  const membersSection = el("section", "details-section");
  const membersHead = el("div", "details-section-head");
  membersHead.append(el("span", "", `Участники · ${members.length}`));
  if (conversation.kind === "group" && state.details.can_manage) {
    const add = el("button", "text-btn", "Добавить");
    add.type = "button";
    add.addEventListener("click", () => openPicker({ mode: "add", channelId: conversation.id }));
    membersHead.append(add);
  }
  membersSection.append(membersHead);

  members.forEach((member) => {
    const row = el("div", "member-row");
    row.append(avatarEl(member, { size: 30, online: Boolean(member.online) }));
    const copy = el("div", "member-copy");
    const nameRow = el("b", "", member.full_name);
    copy.append(nameRow);
    const status = el(
      "small",
      member.online ? "online" : "",
      member.online ? "в сети" : lastSeenLabel(member.last_seen_at)
    );
    copy.append(status);
    row.append(copy);
    if (member.member_role === "owner") row.append(el("span", "owner-mark", "владелец"));

    const canRemove =
      conversation.kind === "group" &&
      state.details.can_manage &&
      member.id !== state.me?.id;
    if (canRemove) {
      const remove = el("button", "member-remove");
      remove.type = "button";
      remove.title = "Удалить из группы";
      remove.setAttribute("aria-label", `Удалить ${member.full_name} из группы`);
      remove.append(iconSvg("close"));
      remove.addEventListener("click", () => removeMember(member));
      row.append(remove);
    }
    membersSection.append(row);
  });
  panel.append(membersSection);

  const actions = el("section", "details-section");
  const actionsHead = el("div", "details-section-head");
  actionsHead.append(el("span", "", "Действия"));
  actions.append(actionsHead);
  const actionBox = el("div", "details-actions");

  const mute = el("button");
  mute.type = "button";
  mute.append(iconSvg(conversation.muted ? "bell" : "bellOff"));
  mute.append(document.createTextNode(conversation.muted ? "Включить уведомления" : "Выключить уведомления"));
  mute.addEventListener("click", () => toggleMute(conversation.muted));
  actionBox.append(mute);

  if (conversation.kind === "group" && state.details.can_manage) {
    const rename = el("button");
    rename.type = "button";
    rename.append(iconSvg("pencil"));
    rename.append(document.createTextNode("Переименовать группу"));
    rename.addEventListener("click", () => {
      state.renaming = true;
      renderDetails();
    });
    actionBox.append(rename);
  }

  const copyLink = el("button");
  copyLink.type = "button";
  copyLink.append(iconSvg("copy"));
  copyLink.append(document.createTextNode("Скопировать ссылку"));
  copyLink.addEventListener("click", copyConversationLink);
  actionBox.append(copyLink);

  if (conversation.kind === "group") {
    const leave = el("button", "danger");
    leave.type = "button";
    leave.append(iconSvg("leave"));
    leave.append(document.createTextNode("Покинуть группу"));
    leave.addEventListener("click", leaveConversation);
    actionBox.append(leave);
  }
  actions.append(actionBox);

  if (state.renaming && conversation.kind === "group" && state.details.can_manage) {
    const form = el("div", "details-rename");
    const input = document.createElement("input");
    input.value = conversation.title;
    input.maxLength = 80;
    input.setAttribute("aria-label", "Новое название группы");
    const buttons = el("div", "details-rename-actions");
    const save = el("button", "primary", "Сохранить");
    save.type = "button";
    const cancel = el("button", "ghost", "Отмена");
    cancel.type = "button";
    cancel.addEventListener("click", () => {
      state.renaming = false;
      renderDetails();
    });
    save.addEventListener("click", () => renameConversation(input.value));
    buttons.append(save, cancel);
    form.append(input, buttons);
    actions.append(form);
    requestAnimationFrame(() => input.focus());
  }
  panel.append(actions);

  const meta = el("section", "details-section");
  const metaHead = el("div", "details-section-head");
  metaHead.append(el("span", "", "О диалоге"));
  meta.append(metaHead);
  const info = el("div", "details-meta");
  const kindText =
    conversation.kind === "channel" ? "Общий канал" : conversation.kind === "group" ? "Группа" : "Личный диалог";
  const line1 = el("span");
  line1.append(document.createTextNode("Тип: "));
  line1.append(el("b", "", kindText));
  info.append(line1);
  const line2 = el("span");
  line2.append(document.createTextNode("Создан: "));
  line2.append(el("b", "", fullStamp(conversation.created_at)));
  info.append(line2);
  meta.append(info);
  panel.append(meta);
}

async function toggleMute(muted) {
  if (!state.activeId) return;
  try {
    const data = await api(`/chat/conversations/${state.activeId}/mute`, {
      method: "POST",
      body: { muted: !muted },
    });
    const updated = data.conversation;
    state.activeConv = updated;
    const index = state.conversations.findIndex((conv) => conv.id === updated.id);
    if (index >= 0) state.conversations[index] = updated;
    state.details.conversation = updated;
    renderSidebar();
    renderDetails();
    refreshTotalsFromState();
    toast(updated.muted ? "Уведомления по диалогу выключены" : "Уведомления включены");
  } catch (error) {
    toast(error.message, true);
  }
}

async function renameConversation(title) {
  const clean = String(title || "").trim();
  if (clean.length < 2) {
    toast("Название — от 2 до 80 символов", true);
    return;
  }
  try {
    const details = await api(`/chat/conversations/${state.activeId}`, {
      method: "PATCH",
      body: { title: clean },
    });
    state.details = details;
    state.activeConv = details.conversation;
    state.renaming = false;
    updateHead();
    renderDetails();
    await refreshConversations();
    toast("Название обновлено");
  } catch (error) {
    toast(error.message, true);
  }
}

async function removeMember(member) {
  if (!window.confirm(`Удалить ${member.full_name} из группы?`)) return;
  try {
    const details = await api(
      `/chat/conversations/${state.activeId}/members/${member.id}`,
      { method: "DELETE" }
    );
    state.details = details;
    state.activeConv = details.conversation;
    updateHead();
    renderDetails();
    await refreshConversations();
    toast("Участник удалён");
  } catch (error) {
    toast(error.message, true);
  }
}

async function leaveConversation() {
  if (!state.activeId) return;
  if (!window.confirm("Покинуть группу? Вы перестанете получать сообщения.")) return;
  const channel = state.activeId;
  try {
    await api(`/chat/conversations/${channel}/leave`, { method: "POST" });
    state.conversations = state.conversations.filter((conv) => conv.id !== channel);
    closeConversation();
    refreshConversations().catch(() => {});
    toast("Вы покинули группу");
  } catch (error) {
    toast(error.message, true);
  }
}

async function copyConversationLink() {
  if (!state.activeId) return;
  const link = `${window.location.origin}/chat?conv=${state.activeId}`;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(link);
    } else {
      const field = document.createElement("textarea");
      field.value = link;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.append(field);
      field.select();
      document.execCommand("copy");
      field.remove();
    }
    toast("Ссылка на диалог скопирована");
  } catch (error) {
    toast("Не удалось скопировать ссылку", true);
  }
}

/* ------------------------------- меню чата -------------------------------- */

function closeChatMenu() {
  $("chatMenu").classList.add("hidden");
  $("chatMenuBtn").setAttribute("aria-expanded", "false");
}

function toggleChatMenu() {
  const menu = $("chatMenu");
  const willOpen = menu.classList.contains("hidden");
  if (!willOpen) {
    closeChatMenu();
    return;
  }
  const conv = state.activeConv;
  if (!conv) return;
  menu.replaceChildren();

  const searchItem = el("button");
  searchItem.type = "button";
  searchItem.append(iconSvg("search"));
  searchItem.append(document.createTextNode("Поиск в диалоге"));
  searchItem.addEventListener("click", () => {
    closeChatMenu();
    openChatSearch();
  });
  menu.append(searchItem);

  const detailsItem = el("button");
  detailsItem.type = "button";
  detailsItem.append(iconSvg("users"));
  detailsItem.append(document.createTextNode("Участники"));
  detailsItem.addEventListener("click", () => {
    closeChatMenu();
    if (!state.detailsOpen) toggleDetails();
  });
  menu.append(detailsItem);

  const muteItem = el("button");
  muteItem.type = "button";
  muteItem.append(iconSvg(conv.muted ? "bell" : "bellOff"));
  muteItem.append(document.createTextNode(conv.muted ? "Включить уведомления" : "Выключить уведомления"));
  muteItem.addEventListener("click", () => {
    closeChatMenu();
    toggleMute(conv.muted);
  });
  menu.append(muteItem);

  menu.append(el("hr"));

  const copyItem = el("button");
  copyItem.type = "button";
  copyItem.append(iconSvg("link"));
  copyItem.append(document.createTextNode("Скопировать ссылку"));
  copyItem.addEventListener("click", () => {
    closeChatMenu();
    copyConversationLink();
  });
  menu.append(copyItem);

  if (conv.kind === "group") {
    const leaveItem = el("button", "danger");
    leaveItem.type = "button";
    leaveItem.append(iconSvg("leave"));
    leaveItem.append(document.createTextNode("Покинуть группу"));
    leaveItem.addEventListener("click", () => {
      closeChatMenu();
      leaveConversation();
    });
    menu.append(leaveItem);
  }

  menu.classList.remove("hidden");
  $("chatMenuBtn").setAttribute("aria-expanded", "true");
}

/* ---------------------------- поиск в диалоге ----------------------------- */

function openChatSearch() {
  $("chatSearchBar").classList.remove("hidden");
  $("chatSearchInput").focus();
}

function closeChatSearch() {
  $("chatSearchBar").classList.add("hidden");
  $("chatSearchResults").classList.add("hidden");
  $("chatSearchResults").replaceChildren();
  $("chatSearchInput").value = "";
}

async function searchInConversation(query) {
  const text = String(query || "").trim();
  const results = $("chatSearchResults");
  const seq = ++state.chatSearchSeq;
  if (text.length < 2) {
    results.classList.add("hidden");
    results.replaceChildren();
    return;
  }
  if (!state.activeId) return;
  try {
    const data = await api(
      `/chat/conversations/${state.activeId}/messages?q=${encodeURIComponent(text)}&limit=50`
    );
    if (seq !== state.chatSearchSeq) return;
    renderChatSearchResults(data.messages || [], text);
  } catch (error) {
    toast(error.message, true);
  }
}

function renderChatSearchResults(messages, query) {
  const box = $("chatSearchResults");
  box.replaceChildren();
  if (!messages.length) {
    box.append(el("p", "search-empty", "В этом диалоге ничего не нашлось."));
    box.classList.remove("hidden");
    return;
  }
  messages
    .slice()
    .reverse()
    .forEach((message) => {
      const button = el("button", "search-result");
      button.type = "button";
      button.append(
        avatarEl(message.sender || { full_name: "Сотрудник", initials: "??" }, { size: 28 })
      );
      const copy = el("div", "search-result-copy");
      const name = el("b", "", message.sender?.full_name || "Система");
      copy.append(name);
      copy.append(el("small", "", fullStamp(message.created_at)));
      const paragraph = el("p");
      highlightQuery(paragraph, message.body || "Вложение", query);
      copy.append(paragraph);
      button.append(copy);
      button.addEventListener("click", () => {
        closeChatSearch();
        scrollToMessage(message.id, { flash: true });
      });
      box.append(button);
    });
  box.classList.remove("hidden");
}

/* ----------------------------- глобальный поиск ---------------------------- */

let convSearchTimer = null;

function clearConvSearch() {
  const input = $("convSearch");
  if (input) input.value = "";
  $("convSearchClear")?.classList.add("hidden");
  $("searchPanel")?.classList.add("hidden");
  $("convList")?.classList.remove("hidden");
  clearTimeout(state.searchTimer);
  state.searchSeq += 1;
}

function handleConvSearchInput() {
  const input = $("convSearch");
  const query = input.value.trim();
  $("convSearchClear").classList.toggle("hidden", !query);
  clearTimeout(state.searchTimer);

  if (query.length < 2) {
    $("searchPanel").classList.add("hidden");
    $("convList").classList.remove("hidden");
    return;
  }
  $("convList").classList.add("hidden");
  $("searchPanel").classList.remove("hidden");
  $("searchPanel").replaceChildren(el("p", "search-empty", "Ищем…"));

  state.searchTimer = setTimeout(() => runGlobalSearch(query), 320);
}

async function runGlobalSearch(query) {
  const seq = ++state.searchSeq;
  const local = state.conversations.filter((conv) => {
    const haystack = `${conv.title} ${conversationPreview(conv)}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  });
  let results = [];
  try {
    const data = await api(`/chat/search?q=${encodeURIComponent(query)}&limit=40`);
    results = data.results || [];
  } catch (error) {
    if (seq !== state.searchSeq) return;
    $("searchPanel").replaceChildren(el("p", "chat-error", error.message));
    return;
  }
  if (seq !== state.searchSeq) return;
  renderGlobalSearch(query, local, results);
}

function renderGlobalSearch(query, local, results) {
  const panel = $("searchPanel");
  panel.replaceChildren();

  if (local.length) {
    const section = el("section", "global-section");
    const head = el("div", "global-section-head", "Диалоги");
    section.append(head);
    local.slice(0, 6).forEach((conv) => {
      const button = el("button", "global-result");
      button.type = "button";
      const top = el("div", "result-top");
      top.append(el("b", "", conv.title));
      top.append(el("time", "", listTime(conv.last_message?.created_at || conv.created_at)));
      button.append(top);
      const preview = el("p");
      highlightQuery(preview, conversationPreview(conv), query);
      button.append(preview);
      button.addEventListener("click", () => openConversation(conv.id));
      section.append(button);
    });
    panel.append(section);
  }

  if (results.length) {
    const section = el("section", "global-section");
    const head = el("div", "global-section-head", "Сообщения");
    section.append(head);
    results.forEach((result) => {
      const button = el("button", "global-result");
      button.type = "button";
      const top = el("div", "result-top");
      top.append(el("b", "", result.channel_title));
      top.append(el("time", "", listTime(result.created_at)));
      button.append(top);
      button.append(el("small", "", result.sender_name));
      const snippet = el("p");
      highlightQuery(snippet, result.snippet, query);
      button.append(snippet);
      button.addEventListener("click", () => {
        if (result.channel_id === state.activeId) {
          clearConvSearch();
          scrollToMessage(result.message_id, { flash: true });
        } else {
          openConversation(result.channel_id, { aroundId: result.message_id });
        }
      });
      section.append(button);
    });
    panel.append(section);
  }

  if (!local.length && !results.length) {
    panel.append(
      el("p", "search-empty", `По запросу «${query}» ничего не нашлось. Попробуйте другое слово.`)
    );
  }
}

function highlightQuery(container, text, query) {
  const value = String(text || "");
  const needle = String(query || "");
  if (!needle) {
    container.textContent = value;
    return;
  }
  const lower = value.toLowerCase();
  const target = needle.toLowerCase();
  let index = 0;
  while (index < value.length) {
    const found = lower.indexOf(target, index);
    if (found < 0) {
      container.append(document.createTextNode(value.slice(index)));
      break;
    }
    if (found > index) container.append(document.createTextNode(value.slice(index, found)));
    container.append(el("mark", "", value.slice(found, found + needle.length)));
    index = found + needle.length;
  }
}

/* ------------------------------- новый чат -------------------------------- */

function openPicker(options = {}) {
  state.picker = {
    open: true,
    mode: options.mode || "create",
    kind: options.mode === "add" ? "group" : "direct",
    channelId: options.channelId || null,
    selected: new Set(),
    query: "",
  };
  const addMode = state.picker.mode === "add";
  $("newChatEyebrow").textContent = addMode ? "Участники" : "Новый разговор";
  $("newChatTitle").textContent = addMode ? "Кого добавить?" : "Кому написать?";
  $("newChatSub").textContent = addMode
    ? "Выберите коллег — они получат доступ к истории группы."
    : "Личный диалог или группа для рабочей задачи.";
  $("newChatTabs").classList.toggle("hidden", addMode);
  $("groupTitleWrap").classList.add("hidden");
  $("groupTitle").value = "";
  $("peopleSearch").value = "";
  $("createChat").disabled = true;
  $("newChatModal").classList.remove("hidden");
  document.body.style.overflow = "hidden";
  renderPeopleList();
  requestAnimationFrame(() => $("peopleSearch").focus());
}

function closePicker() {
  state.picker.open = false;
  $("newChatModal").classList.add("hidden");
  document.body.style.overflow = "";
}

function pickerContacts() {
  let people = state.contacts.slice();
  if (state.picker.mode === "add" && state.details) {
    const existing = new Set((state.details.members || []).map((member) => member.id));
    people = people.filter((person) => !existing.has(person.id));
  }
  const query = state.picker.query.trim().toLowerCase();
  if (query) {
    people = people.filter((person) => person.full_name.toLowerCase().includes(query));
  }
  return people;
}

function renderPeopleList() {
  const list = $("peopleList");
  list.replaceChildren();
  const people = pickerContacts();
  if (!people.length) {
    list.append(
      el("p", "search-empty", "Сотрудники не найдены. Возможно, все уже в этом диалоге.")
    );
    updatePickerState();
    return;
  }
  people.forEach((person) => {
    const selected = state.picker.selected.has(person.id);
    const button = el("button", "person-option" + (selected ? " selected" : ""));
    button.type = "button";
    button.setAttribute("aria-pressed", String(selected));
    button.append(avatarEl(person, { size: 30, online: Boolean(person.online) }));
    const copy = el("div", "person-copy");
    copy.append(el("b", "", person.full_name));
    copy.append(el("small", person.online ? "online" : "", person.online ? "в сети" : roleLabel(person.role)));
    button.append(copy);
    const check = el("span", "person-check");
    check.append(iconSvg("check"));
    button.append(check);
    button.addEventListener("click", () => {
      if (state.picker.mode === "create" && state.picker.kind === "direct") {
        state.picker.selected = new Set([person.id]);
      } else if (selected) {
        state.picker.selected.delete(person.id);
      } else {
        state.picker.selected.add(person.id);
      }
      renderPeopleList();
    });
    list.append(button);
  });
  updatePickerState();
}

function updatePickerState() {
  const button = $("createChat");
  const hint = $("newChatHint");
  const count = state.picker.selected.size;
  if (state.picker.mode === "add") {
    button.disabled = count === 0;
    hint.textContent = count
      ? `Выбрано: ${count}. Они увидят историю группы.`
      : "Выберите хотя бы одного коллегу.";
    return;
  }
  if (state.picker.kind === "direct") {
    button.disabled = count !== 1;
    button.textContent = "Открыть диалог";
    hint.textContent = count ? "Личный диалог с выбранным сотрудником." : "Выберите одного сотрудника.";
  } else {
    const title = $("groupTitle").value.trim();
    button.disabled = count === 0 || title.length < 2;
    button.textContent = "Создать группу";
    hint.textContent = title.length < 2 ? "Придумайте название — от 2 символов." : `Участников: ${count + 1}.`;
  }
}

async function createFromPicker() {
  if (state.picker.mode === "add") {
    if (!state.picker.selected.size) return;
    try {
      const details = await api(
        `/chat/conversations/${state.picker.channelId}/members`,
        { method: "POST", body: { employee_ids: Array.from(state.picker.selected) } }
      );
      state.details = details;
      state.activeConv = details.conversation;
      closePicker();
      updateHead();
      renderDetails();
      await refreshConversations();
      toast("Участники добавлены");
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }

  const kind = state.picker.kind;
  const title = kind === "group" ? $("groupTitle").value.trim() : "";
  if (kind === "group" && title.length < 2) {
    toast("Название группы — от 2 до 80 символов", true);
    return;
  }
  const button = $("createChat");
  button.disabled = true;
  try {
    const data = await api("/chat/conversations", {
      method: "POST",
      body: {
        kind,
        title,
        employee_ids: Array.from(state.picker.selected),
      },
    });
    closePicker();
    await refreshConversations();
    openConversation(data.conversation.id);
    toast(kind === "group" ? "Группа создана" : "Диалог открыт");
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

/* ------------------------------- композер UX ------------------------------ */

function noteTyping() {
  if (!state.activeId || state.editing) return;
  const now = Date.now();
  if (now - state.typingSentAt < 2600) return;
  state.typingSentAt = now;
  api(`/chat/conversations/${state.activeId}/typing`, { method: "POST" }).catch(() => {});
}

function setPendingFile(file) {
  if (!file) return;
  if (file.size > (state.limits.upload_mb || 10) * 1024 * 1024) {
    toast(`Файл больше ${state.limits.upload_mb} МБ`, true);
    return;
  }
  const extension = (file.name.split(".").pop() || "").toLowerCase();
  const blocked = [
    "html", "htm", "xhtml", "svg", "js", "mjs", "exe", "msi", "bat", "cmd",
    "ps1", "vbs", "scr", "com", "dll", "jar", "lnk", "hta", "reg", "sh",
  ];
  if (blocked.includes(extension)) {
    toast("Такие файлы нельзя отправлять", true);
    return;
  }
  state.pendingFile = file;
  renderComposerState();
}

function insertEmoji(emoji) {
  const input = $("composerInput");
  const start = input.selectionStart || 0;
  const end = input.selectionEnd || 0;
  input.value = input.value.slice(0, start) + emoji + input.value.slice(end);
  input.setSelectionRange(start + emoji.length, start + emoji.length);
  input.focus();
  resizeInput();
  updateComposerLimit();
}

function buildEmojiPop() {
  const pop = $("emojiPop");
  const emojis = [
    "😀", "😄", "🙂", "😉", "😎", "🤔", "🙌", "👍",
    "👋", "🔥", "✅", "❌", "⚠️", "📌", "📎", "📞",
    "💬", "📝", "📅", "⏰", "🚀", "💡", "🎯", "❤️",
    "😅", "😮", "😢", "🙏", "💪", "🤝", "☕", "⭐",
  ];
  emojis.forEach((emoji) => {
    const button = el("button", "", emoji);
    button.type = "button";
    button.setAttribute("aria-label", `Вставить ${emoji}`);
    button.addEventListener("click", () => {
      insertEmoji(emoji);
      pop.classList.add("hidden");
      $("emojiBtn").setAttribute("aria-expanded", "false");
    });
    pop.append(button);
  });
}

/* ------------------------------- клавиатура ------------------------------- */

function handleComposerKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    if (state.mention.open) {
      event.preventDefault();
      const person = state.mention.items[state.mention.active];
      if (person) insertMention(person);
      return;
    }
    event.preventDefault();
    $("composer").requestSubmit();
    return;
  }
  if (event.key === "Escape") {
    if (state.mention.open) {
      event.preventDefault();
      closeMentionPop();
    } else if (state.editing || state.replyTo) {
      event.preventDefault();
      clearComposerModes();
    }
    return;
  }
  if (state.mention.open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
    event.preventDefault();
    const total = state.mention.items.length;
    state.mention.active =
      (state.mention.active + (event.key === "ArrowDown" ? 1 : -1) + total) % total;
    renderMentionPop();
  }
}

/* --------------------------------- события -------------------------------- */

function bindEvents() {
  $("newChat").addEventListener("click", () => openPicker({ mode: "create" }));
  $("closeNewChat").addEventListener("click", closePicker);
  $("newChatModal").addEventListener("click", (event) => {
    if (event.target === $("newChatModal")) closePicker();
  });
  $("createChat").addEventListener("click", createFromPicker);

  document.querySelectorAll(".newchat-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".newchat-tab").forEach((item) => {
        item.classList.toggle("active", item === tab);
        item.setAttribute("aria-selected", String(item === tab));
      });
      state.picker.kind = tab.dataset.kind;
      state.picker.selected = new Set();
      $("groupTitleWrap").classList.toggle("hidden", state.picker.kind !== "group");
      $("peopleList").replaceChildren();
      renderPeopleList();
    });
  });

  $("groupTitle").addEventListener("input", updatePickerState);
  $("peopleSearch").addEventListener("input", () => {
    state.picker.query = $("peopleSearch").value;
    renderPeopleList();
  });

  $("backToChats").addEventListener("click", () => {
    if (window.matchMedia("(max-width: 960px)").matches) {
      showEmptyPageOnMobile();
    }
  });

  $("toggleDetails").addEventListener("click", toggleDetails);
  $("toggleSearch").addEventListener("click", () => {
    if ($("chatSearchBar").classList.contains("hidden")) openChatSearch();
    else closeChatSearch();
  });
  $("chatSearchClose").addEventListener("click", closeChatSearch);
  $("chatSearchInput").addEventListener("input", () => {
    clearTimeout(state.chatSearchTimer);
    const value = $("chatSearchInput").value;
    state.chatSearchTimer = setTimeout(() => searchInConversation(value), 320);
  });
  $("chatMenuBtn").addEventListener("click", toggleChatMenu);

  $("composer").addEventListener("submit", submitComposer);
  const input = $("composerInput");
  input.addEventListener("keydown", handleComposerKeydown);
  input.addEventListener("input", () => {
    resizeInput();
    updateComposerLimit();
    openMentionPop();
    if (input.value.trim()) noteTyping();
  });
  input.addEventListener("paste", (event) => {
    const items = Array.from(event.clipboardData?.items || []);
    const fileItem = items.find((item) => item.kind === "file");
    if (fileItem) {
      const file = fileItem.getAsFile();
      if (file) {
        event.preventDefault();
        setPendingFile(file);
      }
    }
  });
  input.addEventListener("blur", () => setTimeout(closeMentionPop, 120));

  $("attachBtn").addEventListener("click", () => $("fileInput").click());
  $("fileInput").addEventListener("change", () => {
    const file = $("fileInput").files?.[0];
    if (file) setPendingFile(file);
  });

  $("emojiBtn").addEventListener("click", () => {
    const pop = $("emojiPop");
    const open = pop.classList.contains("hidden");
    pop.classList.toggle("hidden", !open);
    $("emojiBtn").setAttribute("aria-expanded", String(open));
  });

  $("cancelEdit").addEventListener("click", clearComposerModes);

  $("sendBtn").addEventListener("click", (event) => {
    if (state.sending) {
      event.preventDefault();
    }
  });

  $("jumpLatest").addEventListener("click", () => {
    scrollToBottom(true);
    markReadIfVisible();
  });

  $("convSearch").addEventListener("input", handleConvSearchInput);
  $("convSearchClear").addEventListener("click", () => {
    clearConvSearch();
    $("convSearch").focus();
  });

  $("messageScroll").addEventListener("scroll", () => {
    const near = isNearBottom();
    state.atBottom = near;
    if (near) $("jumpLatest").classList.add("hidden");
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".chat-menu-wrap")) closeChatMenu();
    if (!event.target.closest("#emojiPop, #emojiBtn")) {
      $("emojiPop")?.classList.add("hidden");
      $("emojiBtn")?.setAttribute("aria-expanded", "false");
    }
    if (!event.target.closest("#mentionPop, #composerInput")) closeMentionPop();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!$("newChatModal").classList.contains("hidden")) {
        closePicker();
        return;
      }
      if (state.mention.open) {
        closeMentionPop();
        return;
      }
      closeChatMenu();
      if (!$("emojiPop").classList.contains("hidden")) {
        $("emojiPop").classList.add("hidden");
        $("emojiBtn").setAttribute("aria-expanded", "false");
      }
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      pollMessages();
      refreshConversations().catch(() => {});
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
      const tag = (event.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      event.preventDefault();
      $("convSearch").focus();
    }
  });
}

function showEmptyPageOnMobile() {
  state.activeId = null;
  state.activeConv = null;
  state.details = null;
  state.messages = [];
  state.lastId = 0;
  state.detailsOpen = false;
  $("details").hidden = true;
  $("messenger").classList.remove("with-details", "chat-open");
  showEmpty();
  renderSidebar();
  history.replaceState(null, "", "/chat");
}

/* --------------------------------- старт ---------------------------------- */

async function boot() {
  buildEmojiPop();
  bindEvents();
  try {
    const data = await api("/chat/bootstrap");
    state.me = data.me;
    state.contacts = data.contacts || [];
    state.conversations = data.conversations || [];
    state.totals = data.totals || { unread: 0, mentions: 0 };
    state.timezone = data.timezone || state.timezone;
    state.limits = data.limits || state.limits;
    $("composerInput").maxLength = state.limits.message_chars || 4000;
    renderMe();
    renderSidebar();
    renderTotals();
    renderEmptyChannels();
    updateTitle();
    setConnection(true);
  } catch (error) {
    setConnection(false);
    toast(error.message || "Не удалось загрузить мессенджер", true);
    return;
  }

  const params = new URLSearchParams(window.location.search);
  const fromLink = Number(params.get("conv"));
  const toPerson = Number(params.get("to"));
  if (fromLink) {
    openConversation(fromLink);
  } else if (toPerson && state.contacts.some((person) => person.id === toPerson)) {
    try {
      const data = await api("/chat/conversations", {
        method: "POST",
        body: { kind: "direct", employee_ids: [toPerson] },
      });
      await refreshConversations();
      openConversation(data.conversation.id);
    } catch (error) {
      toast(error.message, true);
    }
  } else {
    showEmpty();
  }

  scheduleMessagePoll(1200);
  scheduleListPoll(6000);
}

boot();
