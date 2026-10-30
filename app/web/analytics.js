const state = { days: 14, data: null, loading: false };

const $ = (id) => document.getElementById(id);
const num = (value) => (value == null ? "—" : new Intl.NumberFormat("ru-RU").format(value));
const pct = (value) => (value == null ? "—" : `${String(value).replace(".", ",")}%`);

const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const BLUE = "#1f4bff";
const GREEN = "#0f7a55";

function dayLabel(iso, weekday) {
  const [, month, day] = iso.split("-");
  const short = `${Number(day)} ${MONTHS[Number(month) - 1]}`;
  return weekday ? `${WEEKDAYS[weekday - 1]}, ${short}` : short;
}

function periodChips() {
  const items = [
    [7, "7 дней"],
    [14, "14 дней"],
    [30, "30 дней"],
  ];
  $("periods").innerHTML = items
    .map(
      ([days, title]) =>
        `<button type="button" class="chip ${state.days === days ? "active" : ""}" data-days="${days}" aria-pressed="${
          state.days === days
        }">${title}</button>`
    )
    .join("");
  $("periods")
    .querySelectorAll(".chip")
    .forEach((chip) => chip.addEventListener("click", () => load(Number(chip.dataset.days))));
}

async function load(days = state.days) {
  if (state.loading) return;
  state.loading = true;
  state.days = days;
  $("error").hidden = true;
  try {
    const response = await fetch(`/api/v1/analytics?days=${days}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();
    render(state.data);
  } catch (error) {
    $("error").hidden = false;
    $("error").textContent = `Не удалось загрузить аналитику: ${error.message}`;
  } finally {
    state.loading = false;
    periodChips();
  }
}

function render(data) {
  const t = data.totals;

  $("kpis").innerHTML = [
    `<div class="stat"><b>${num(t.tasks)}</b><span>задач</span></div>`,
    `<div class="stat"><b>${num(t.due_today)}</b><span>срок сегодня</span></div>`,
    `<div class="stat danger"><b>${num(t.overdue)}</b><span>просрочено</span></div>`,
    `<div class="stat ok"><b>${num(t.closed)}</b><span>выполнено</span></div>`,
  ].join("");

  const generated = new Date(data.generated_at);
  $("stamp").textContent = `обновлено ${generated.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  })} · ${data.timezone}`;

  $("chartSub").textContent = `Окно ${data.period_days} дней вокруг сегодняшнего`;
  drawChart(data.series);

  const v = data.by_verification;
  const total = v.pending + v.confirmed + v.refuted || 1;
  $("verify").innerHTML = [
    `<div class="an-pill"><b>${num(v.pending)}</b><span>без проверки клиентом · ${Math.round(
      (v.pending / total) * 100
    )}%</span></div>`,
    `<div class="an-pill ok"><b>${num(v.confirmed)}</b><span>подтверждено · ${Math.round(
      (v.confirmed / total) * 100
    )}%</span></div>`,
    `<div class="an-pill bad"><b>${num(v.refuted)}</b><span>не выполнено · ${Math.round(
      (v.refuted / total) * 100
    )}%</span></div>`,
  ].join("");

  const ct = data.close_time;
  $("closeTime").innerHTML = [
    `<div class="an-pill"><b>${
      ct.median_hours == null ? "—" : `${String(ct.median_hours).replace(".", ",")} ч`
    }</b><span>медиана закрытия</span></div>`,
    `<div class="an-pill"><b>${
      ct.avg_hours == null ? "—" : `${String(ct.avg_hours).replace(".", ",")} ч`
    }</b><span>среднее</span></div>`,
    `<div class="an-pill"><b>${num(ct.closed_count)}</b><span>закрытых задач</span></div>`,
  ].join("");

  const maxType = Math.max(1, ...data.by_type.map((item) => item.count));
  $("types").innerHTML = data.by_type.length
    ? data.by_type
        .map(
          (item) => `
        <div class="an-type-row">
          <div>
            <div class="an-type-name">${escapeHtml(item.title)}</div>
            <div class="an-type-bar"><i style="width:${(item.count / maxType) * 100}%"></i></div>
          </div>
          <b>${num(item.count)}</b>
        </div>`
        )
        .join("")
    : `<div class="an-empty">Задач пока нет.</div>`;

  $("operators").innerHTML = data.operators.length
    ? `<table class="an-table">
         <thead><tr><th>Оператор</th><th class="num">Открыто</th><th class="num">Просрочено</th><th class="num">Выполнено</th></tr></thead>
         <tbody>
           ${data.operators
             .map(
               (op) => `<tr>
                 <td>#${escapeHtml(String(op.operator_id))}</td>
                 <td class="num">${num(op.open)}</td>
                 <td class="num ${op.overdue ? "danger" : ""}">${num(op.overdue)}</td>
                 <td class="num ok">${num(op.done)}</td>
               </tr>`
             )
             .join("")}
         </tbody>
       </table>`
    : `<div class="an-empty">Нет данных по операторам.</div>`;

  const overdueShare = t.overdue_share == null ? "—" : pct(t.overdue_share);
  $("foot").textContent =
    `Просрочено ${overdueShare} от всех задач · данные собираются из звонков, ` +
    `которые программа-отправитель присылает на вебхук`;
}

function drawChart(series) {
  const svg = $("chart");
  const W = 760;
  const H = 260;
  const padLeft = 46;
  const padRight = 12;
  const padTop = 14;
  const padBottom = 36;
  const innerW = W - padLeft - padRight;
  const innerH = H - padTop - padBottom;
  const max = Math.max(1, ...series.map((d) => Math.max(d.due || 0, d.closed || 0)));
  const step = innerW / Math.max(1, series.length);
  const barW = Math.min(20, step * 0.30);

  const parts = [];
  for (let i = 0; i <= 4; i += 1) {
    const value = Math.round((max / 4) * i);
    const y = padTop + innerH - (value / max) * innerH;
    parts.push(
      `<line x1="${padLeft}" y1="${y}" x2="${W - padRight}" y2="${y}" stroke="rgba(21,24,29,0.08)" stroke-width="1"/>`
    );
    parts.push(
      `<text x="${padLeft - 10}" y="${y + 4}" text-anchor="end" font-size="11" fill="#7d7f77">${value}</text>`
    );
  }

  series.forEach((day, index) => {
    const cx = padLeft + step * index + step / 2;
    const dueH = ((day.due || 0) / max) * innerH;
    const closedH = (day.closed / max) * innerH;
    const baseY = padTop + innerH;

    parts.push(
      `<rect x="${cx - barW - 2}" y="${baseY - dueH}" width="${barW}" height="${Math.max(
        dueH,
        day.due ? 2 : 0
      )}" rx="3" fill="${BLUE}"/>`
    );
    parts.push(
      `<rect x="${cx + 2}" y="${baseY - closedH}" width="${barW}" height="${Math.max(
        closedH,
        day.closed ? 2 : 0
      )}" rx="3" fill="${GREEN}"/>`
    );

    if (series.length <= 15 || index % 2 === 0) {
      parts.push(
        `<text x="${cx}" y="${baseY + 19}" text-anchor="middle" font-size="10.5" fill="#7d7f77">${dayLabel(
          day.date,
          series.length <= 8 ? day.weekday : 0
        )}</text>`
      );
    }
    parts.push(`<title>${day.date}: срок ${day.due ?? 0}, закрыто ${day.closed}</title>`);
  });

  parts.push(
    `<line x1="${padLeft}" y1="${padTop + innerH}" x2="${W - padRight}" y2="${
      padTop + innerH
    }" stroke="rgba(21,24,29,0.16)" stroke-width="1"/>`
  );

  svg.innerHTML = parts.join("");
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
  );
}

$("refresh").addEventListener("click", () => load());
periodChips();
load(14);
setInterval(() => load(), 60000);
