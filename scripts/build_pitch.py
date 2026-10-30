"""Сборка презентации на защиту (7 минут).

Запуск: python scripts/build_pitch.py
Результат: docs/Презентация_7_минут.pptx

Палитра и типографика заданы константами ниже — менять только здесь.
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "Презентация_7_минут.pptx"
SHOT = ROOT / "docs" / "img" / "dashboard.png"

# --- палитра -----------------------------------------------------------------
BG_LIGHT = RGBColor(0xF7, 0xF7, 0xFB)
BG_DARK = RGBColor(0x14, 0x16, 0x2B)
PANEL = RGBColor(0x1E, 0x21, 0x40)
PRIMARY = RGBColor(0x4F, 0x46, 0xE5)
PRIMARY_DARK = RGBColor(0x37, 0x30, 0xA3)
ACCENT = RGBColor(0xF5, 0x9E, 0x0B)
TEXT = RGBColor(0x1B, 0x1F, 0x2A)
MUTED = RGBColor(0x6B, 0x72, 0x80)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CARD = RGBColor(0xFF, 0xFF, 0xFF)
SOFT = RGBColor(0xEE, 0xF0, 0xFF)
DANGER = RGBColor(0xDC, 0x26, 0x26)
LINE = RGBColor(0xE5, 0xE7, 0xEF)

FONT = "Segoe UI"
MONO = "Consolas"

W, H, M = 13.333, 7.5, 0.7
CW = W - 2 * M


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    return prs


def blank(prs: Presentation, dark: bool = False):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background.fill
    bg.solid()
    bg.fore_color.rgb = BG_DARK if dark else BG_LIGHT
    return slide


def text(
    slide,
    x,
    y,
    w,
    h,
    value,
    size=18,
    color=TEXT,
    bold=False,
    font=FONT,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    line=1.15,
    space_after=0,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    lines = value.split("\n")
    for i, line_text in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = line
        p.space_after = Pt(space_after)
        run = p.add_run()
        run.text = line_text
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = color
    return box


def shape(slide, kind, x, y, w, h, fill=None, line_color=None, line_w=1.0, radius=None, shadow=False):
    shp = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line_color is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line_color
        shp.line.width = Pt(line_w)
    if radius is not None and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        shp.adjustments[0] = radius
    if not shadow:
        shp.shadow.inherit = False
    if shp.has_text_frame:
        shp.text_frame.text = ""
    return shp


def pill(slide, x, y, w, text_value, fill, color=WHITE, size=10.5):
    h = 0.3
    shp = shape(slide, MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h, fill=fill, radius=0.5)
    tf = shp.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = Inches(0.08)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = text_value
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = True
    run.font.color.rgb = color
    return shp


def title_block(slide, kicker: str, heading: str, dark: bool = False):
    text(slide, M, 0.55, CW, 0.3, kicker.upper(), size=11.5, color=PRIMARY if not dark else ACCENT, bold=True)
    text(slide, M, 0.9, CW, 1.0, heading, size=36, color=WHITE if dark else TEXT, bold=True, line=1.05)


def notes(slide, value: str):
    slide.notes_slide.notes_text_frame.text = value


def footer(slide, value: str, dark: bool = False):
    text(slide, M, H - 0.55, CW, 0.3, value, size=11.5, color=MUTED if not dark else RGBColor(0x9C, 0xA3, 0xAF))


# --------------------------------------------------------------------------- #
# 1. Титул
# --------------------------------------------------------------------------- #
def slide_title(prs):
    s = blank(prs, dark=True)
    text(s, M, 1.15, 7.4, 0.3, "КЕЙС УРАЛМИКРО · ХАКАТОН 2026", size=12, color=ACCENT, bold=True)
    text(s, M, 1.6, 7.6, 2.2, "Сервис контроля\nобещаний", size=52, color=WHITE, bold=True, line=1.02)
    text(
        s,
        M,
        3.95,
        6.9,
        1.0,
        "Расшифровка звонка → найденные обещания →\nзадачи со сроком и статусом",
        size=19,
        color=RGBColor(0xC7, 0xCB, 0xE3),
        line=1.25,
    )

    # мотив: карточка задачи
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 8.05, 1.75, 4.55, 2.75, fill=PANEL, radius=0.06)
    pill(s, 8.35, 2.05, 1.5, "ПРОСРОЧЕНО", DANGER, size=9.5)
    text(s, 8.35, 2.55, 3.9, 0.5, "Перезвонить клиенту", size=21, color=WHITE, bold=True)
    text(s, 8.35, 3.1, 3.95, 0.75, "«Перезвоню вам завтра\nв десять утра»", size=14, color=RGBColor(0xC7, 0xCB, 0xE3), line=1.2)
    text(s, 8.35, 3.95, 3.9, 0.3, "срок: 30 окт, 10:00", size=12, color=RGBColor(0x9C, 0xA3, 0xAF))

    footer(s, "github.com/jabkamamka/promise-control", dark=True)
    notes(
        s,
        "25 секунд. Кейс УралМикро: обещание оператора теряется между звонками. "
        "Мы сделали сервис, который находит обещания в расшифровке и превращает их в задачи со сроком. "
        "Дальше — проблема, решение, демо и ограничения.",
    )


# --------------------------------------------------------------------------- #
# 2. Проблема
# --------------------------------------------------------------------------- #
def slide_problem(prs):
    s = blank(prs)
    title_block(s, "Проблема", "Обещание теряется между звонками")
    text(
        s,
        M,
        2.05,
        6.3,
        1.3,
        "Оператор пообещал перезвонить, выставить счёт или уточнить —\nи это нигде не зафиксировано.",
        size=18,
        color=MUTED,
        line=1.35,
    )

    stats = [
        ("3,6", "обещания на один звонок —\nзамер на 52 расшифровках"),
        ("24 ч", "срок по умолчанию, если\nдата в разговоре не названа"),
        ("7", "типов обещаний: от звонка\nи документов до выезда мастера"),
    ]
    y = 3.35
    for value, label in stats:
        text(s, M, y, 1.55, 0.72, value, size=34, color=ACCENT if value == "3,6" else PRIMARY, bold=True)
        text(s, M + 1.75, y + 0.05, 4.35, 0.7, label, size=13.5, color=MUTED, line=1.25)
        y += 1.1

    # цитата из реального звонка
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 7.55, 2.05, 5.05, 3.55, fill=CARD, radius=0.05, line_color=LINE)
    text(s, 7.9, 2.35, 4.4, 0.3, "ИЗ РАСШИФРОВКИ ЗВОНКА", size=10.5, color=MUTED, bold=True)
    text(s, 7.9, 2.72, 4.4, 1.3, "«Мне нужно уточнить\nу производства. Я вам\nперезвоню в понедельник…»", size=17, color=TEXT, line=1.3)
    text(s, 7.9, 4.2, 4.4, 0.35, "— оператор, 4 минуты разговора", size=12, color=MUTED)
    text(s, 7.9, 4.62, 4.4, 0.6, "Где этот понедельник? Кто проверит?", size=15, color=PRIMARY, bold=True)

    footer(s, "Источник: 52 расшифровки из API УралМикро, прогон сервиса")
    notes(
        s,
        "50 секунд. Проблема не в том, что оператор забыл, а в том, что обещание нигде не зафиксировано. "
        "В среднем 3,6 обещания на звонок. Дальше покажу, как это превращается в задачи.",
    )


# --------------------------------------------------------------------------- #
# 3. Решение
# --------------------------------------------------------------------------- #
def slide_solution(prs):
    s = blank(prs)
    title_block(s, "Решение", "От звонка до закрытой задачи")

    steps = [
        ("1", "Звонок", "POST /webhook/calls\n10 звонков за раз\nповтор не создаёт дублей"),
        ("2", "Поиск", "только реплики оператора\n7 типов обещаний\nсмысл, а не ключевые слова"),
        ("3", "Задача", "срок из фразы\nцитата и номер реплики\nсвой тип через API"),
        ("4", "Статус", "создана → в работе →\nвыполнена\nпросрочка и проверка"),
    ]
    x = M
    box_w, gap = 2.62, 0.42
    for i, (num, head, detail) in enumerate(steps):
        shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, 2.15, box_w, 3.15, fill=CARD, radius=0.06, line_color=LINE)
        circle = shape(s, MSO_SHAPE.OVAL, x + 0.28, 2.45, 0.55, 0.55, fill=PRIMARY)
        tf = circle.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        run = p.add_run()
        run.text = num
        run.font.name = FONT
        run.font.size = Pt(16)
        run.font.bold = True
        run.font.color.rgb = WHITE

        text(s, x + 0.28, 3.15, box_w - 0.5, 0.4, head, size=20, bold=True)
        text(s, x + 0.28, 3.7, box_w - 0.5, 1.55, detail, size=12.5, color=MUTED, line=1.35)
        if i < len(steps) - 1:
            shape(s, MSO_SHAPE.RIGHT_ARROW, x + box_w + 0.11, 3.55, 0.2, 0.22, fill=PRIMARY)
        x += box_w + gap

    text(
        s,
        M,
        5.75,
        CW,
        0.5,
        "Один Python-процесс и SQLite: запускается на школьном ноутбуке одной командой, работает без интернета.",
        size=14.5,
        color=TEXT,
        bold=False,
    )
    footer(s, "Стек: Python 3.11+, FastAPI, SQLite, 119 тестов")
    notes(
        s,
        "55 секунд. Четыре шага: вебхук принимает звонки, детектор ищет обещания только в репликах оператора, "
        "каждое обещание становится задачей со сроком, дальше оператор ведёт статус. "
        "Всё умещается в один процесс — это важно для запуска на школьном компьютере.",
    )


# --------------------------------------------------------------------------- #
# 4. Демо
# --------------------------------------------------------------------------- #
def slide_demo(prs):
    s = blank(prs)
    title_block(s, "Демонстрация", "189 задач из 52 звонков")

    if SHOT.exists():
        pic = s.shapes.add_picture(str(SHOT), Inches(M), Inches(2.0), width=Inches(7.2))
        shape(
            s,
            MSO_SHAPE.RECTANGLE,
            M,
            2.0,
            7.2,
            pic.height / 914400,
            fill=None,
            line_color=LINE,
        )
    else:  # pragma: no cover
        shape(s, MSO_SHAPE.RECTANGLE, M, 2.0, 8.35, 4.6, fill=CARD, line_color=LINE)

    x = M + 7.55
    items = [
        ("Фильтры", "статус, тип, оператор,\nсрок, поиск по цитате"),
        ("Цитата", "у каждой задачи — реплика\nоператора и её номер"),
        ("Статус", "в работу и выполнено\nпрямо из карточки"),
        ("Звонок", "расшифровка целиком,\nобещания подсвечены"),
    ]
    y = 2.05
    for head, detail in items:
        text(s, x, y, 4.2, 0.3, head, size=15, bold=True, color=PRIMARY_DARK)
        text(s, x, y + 0.32, 4.25, 0.8, detail, size=12.5, color=MUTED, line=1.3)
        y += 1.15

    footer(s, "Панель оператора: http://localhost:8080/ · Swagger: /docs")
    notes(
        s,
        "80 секунд. Вот живая панель: 189 задач из 52 звонков, 22 уже просрочены — сервис посчитал сам. "
        "Покажу карточку: тип, срок, цитата, кнопки статуса. Кнопка «звонок» открывает расшифровку "
        "с подсветкой обещаний.",
    )


# --------------------------------------------------------------------------- #
# 5. Как находится обещание
# --------------------------------------------------------------------------- #
def slide_detect(prs):
    s = blank(prs)
    title_block(s, "Как работает поиск", "Обещание — глагол оператора")

    rules = [
        ("Только оператор", "«Я пришлю вам фото» клиента — не обязательство компании"),
        ("Будущее время", "«перезвоню», «отправлю», «уточню»; вопросы и прошедшее время отсекаются"),
        ("Тип по объекту", "документ → выслать, «смс» → напомнить, «выезд» → визит"),
        ("Приоритет", "если в реплике два действия — побеждает то, что клиент увидит сам"),
    ]
    y = 2.05
    for head, detail in rules:
        text(s, M, y, 4.9, 0.3, head, size=15.5, bold=True)
        text(s, M, y + 0.3, 4.95, 0.55, detail, size=12.5, color=MUTED, line=1.3)
        y += 1.05

    # пример: расшифровка
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 6.0, 2.0, 6.6, 4.45, fill=CARD, radius=0.04, line_color=LINE)
    text(s, 6.3, 2.2, 6.0, 0.3, "ОДИН ЗВОНОК — ЧЕТЫРЕ ОБЕЩАНИЯ", size=10.5, color=MUTED, bold=True)

    lines = [
        ("О", "Мне нужно уточнить у производства. Я вам перезвоню в понедельник.", True),
        ("О", "Оформлю повторный выезд и свяжусь с вами завтра.", True),
        ("О", "Не буду гадать, уточню у юристов и вернусь с ответом через день.", True),
        ("О", "Пришлю подробную инструкцию на вашу почту в течение получаса.", True),
        ("К", "Хорошо, жду.", False),
    ]
    y = 2.6
    for speaker, line_text, promise in lines:
        if promise:
            shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 6.25, y - 0.04, 6.1, 0.62, fill=SOFT, radius=0.12)
        text(s, 6.4, y, 0.3, 0.3, speaker, size=10, bold=True, color=PRIMARY if promise else MUTED)
        text(s, 6.75, y, 5.45, 0.6, line_text, size=11.5, color=TEXT if promise else MUTED, line=1.2)
        y += 0.72

    text(s, M, 6.55, 6.3, 0.45, "→ 4 задачи: 2 уточнения, 1 звонок, 1 документ", size=12.5, color=PRIMARY_DARK, bold=True)
    footer(s, "Правила описаны в app/services/taxonomy.py и detect.py — без чёрного ящика")
    notes(
        s,
        "55 секунд. Ключевое: обещание — это глагол оператора в первом лице. Клиентские обещания, вопросы "
        "и прошедшее время не считаются. В одном звонке обычно 3–5 обещаний — каждое становится отдельной задачей. "
        "Тип выбирается по объекту и адресату, спорные случаи решает приоритет.",
    )


# --------------------------------------------------------------------------- #
# 6. Сроки
# --------------------------------------------------------------------------- #
def slide_deadlines(prs):
    s = blank(prs)
    title_block(s, "Сроки", "«Завтра до обеда» = 30 окт, 12:00")

    rows = [
        ("Перезвоню в понедельник", "пн, 18:00", "день недели"),
        ("Отправлю завтра до обеда", "пт, 12:00", "день + время суток"),
        ("Пришлю в течение получаса", "+30 минут", "относительный"),
        ("Вернусь в течение трёх рабочих дней", "+3 рабочих дня, 18:00", "рабочие дни"),
        ("Отправлю до конца недели", "пятница, 18:00", "конец периода"),
        ("Срок не назван", "+24 часа", "по умолчанию"),
    ]

    table_shape = s.shapes.add_table(len(rows) + 1, 3, Inches(M), Inches(2.0), Inches(CW), Inches(3.9))
    table = table_shape.table
    table.columns[0].width = Inches(6.1)
    table.columns[1].width = Inches(3.4)
    table.columns[2].width = Inches(2.4)

    headers = ["Фраза в разговоре", "Срок", "Правило"]
    for j, head in enumerate(headers):
        cell = table.cell(0, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor(0xEF, 0xF0, 0xF6)
        cell.margin_left = Inches(0.12)
        cell.margin_top = cell.margin_bottom = Inches(0.06)
        p = cell.text_frame.paragraphs[0]
        run = p.add_run()
        run.text = head
        run.font.name = FONT
        run.font.size = Pt(11)
        run.font.bold = True
        run.font.color.rgb = MUTED

    for i, (phrase, due, rule) in enumerate(rows, start=1):
        values = [phrase, due, rule]
        for j, value in enumerate(values):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if i % 2 else RGBColor(0xF9, 0xFA, 0xFF)
            cell.margin_left = Inches(0.12)
            cell.margin_top = cell.margin_bottom = Inches(0.08)
            p = cell.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = value
            run.font.name = FONT
            run.font.size = Pt(13.5)
            run.font.bold = j == 1
            run.font.color.rgb = PRIMARY_DARK if j == 1 else (TEXT if j == 0 else MUTED)

    text(
        s,
        7.55,
        6.2,
        5.1,
        0.6,
        "Если срок получился в прошлом —\nсдвигаем на час, а не помечаем просроченным сразу.",
        size=11.5,
        color=MUTED,
        line=1.3,
    )
    footer(s, "Часовой пояс оператора из APP_TIMEZONE · фраза-источник сохраняется в due_hint")
    notes(
        s,
        "45 секунд. Парсер понимает числа словами, дни недели, рабочие дни и концы периодов. "
        "Если срок не назван — 24 часа. Фраза-источник сохраняется, чтобы на защите и в интерфейсе было видно, "
        "почему дедлайн такой.",
    )


# --------------------------------------------------------------------------- #
# 7. Надёжность и расширяемость
# --------------------------------------------------------------------------- #
def slide_reliability(prs):
    s = blank(prs)
    title_block(s, "Надёжность", "Дубли, статусы, новые типы")

    items = [
        ("Защита от дублей", "calls.id + UNIQUE dedupe_key: повторный звонок не создаёт задачи"),
        ("Статусы и история", "создана → в работе → выполнена; просрочка вычисляется и пишется в историю"),
        ("119 тестов", "сроки, детектор, API, идемпотентность, проверка исполнения"),
        ("Свой тип через API", "название, описание, ключевые слова — работает на следующих звонках"),
    ]
    y = 2.05
    for head, detail in items:
        text(s, M, y, 5.4, 0.3, head, size=15.5, bold=True)
        text(s, M, y + 0.3, 5.45, 0.55, detail, size=12.5, color=MUTED, line=1.3)
        if head != items[-1][0]:
            shape(s, MSO_SHAPE.RECTANGLE, M, y + 0.92, 5.45, 0.012, fill=LINE)
        y += 1.08

    # код
    shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 6.55, 2.0, 6.05, 3.7, fill=BG_DARK, radius=0.04)
    text(s, 6.85, 2.2, 5.5, 0.3, "POST /api/v1/promise-types", size=11, color=ACCENT, bold=True, font=MONO)
    code = (
        "{\n"
        '  "title": "Согласовать скидку",\n'
        '  "description": "Оператор обещает\n'
        '    согласовать скидку и вернуться",\n'
        '  "keywords": ["скидк", "согласую"],\n'
        '  "examples": ["Согласую скидку"]\n'
        "}"
    )
    text(s, 6.85, 2.55, 5.45, 2.9, code, size=11.5, color=RGBColor(0xE2, 0xE5, 0xF0), font=MONO, line=1.35)

    text(s, 6.55, 5.85, 6.0, 0.5, "Тип сразу участвует в поиске — перезапуск не нужен", size=12.5, color=PRIMARY_DARK, bold=True)
    footer(s, "Тесты: python -m pytest · API: /docs")
    notes(
        s,
        "45 секунд. Повторная обработка звонка не создаёт дублей — уникальный ключ в базе. Статусы ограничены "
        "правилами переходов, просрочка фиксируется в истории. Новый тип обещания добавляется через API: "
        "описание, ключевые слова, примеры — и он сразу работает.",
    )


# --------------------------------------------------------------------------- #
# 8. Ограничения
# --------------------------------------------------------------------------- #
def slide_limits(prs):
    s = blank(prs)
    title_block(s, "Честно", "Что не сделано и почему")

    rows = [
        ("Проверка исполнения — по правилам", "клиент должен явно сказать «перезвонили» или «не пришёл»"),
        ("Поиск на правилах, а не на большой модели", "нужна объяснимость и работа офлайн; LLM — опциональный второй проход"),
        ("Праздники не учитываются", "нужен производственный календарь РФ"),
        ("SQLite и один процесс", "для нагрузки контакт-центра — PostgreSQL и очередь"),
        ("Часовой пояс один на сервис", "в данных кейса у операторов один пояс"),
    ]
    y = 2.0
    for head, detail in rows:
        text(s, M, y, 4.6, 0.6, head, size=13.5, bold=True, color=TEXT, line=1.2)
        text(s, M + 4.85, y, 6.9, 0.7, detail, size=12.5, color=MUTED, line=1.3)
        shape(s, MSO_SHAPE.RECTANGLE, M, y + 0.82, CW, 0.012, fill=LINE)
        y += 0.95

    text(s, M, 6.75, CW, 0.3, "Дальше: пилот на реальной нагрузке, точность проверки и PostgreSQL", size=13, color=PRIMARY_DARK, bold=True)
    footer(s, "Все ограничения перечислены в README и docs/AI_USAGE.md")
    notes(
        s,
        "40 секунд. Честно про ограничения: проверку исполнения не делали — кейс разрешает; поиск на правилах, "
        "а не на модели; SQLite. Следующий шаг — пилот на реальной нагрузке и замер точности проверки.",
    )


# --------------------------------------------------------------------------- #
# 9. Финал
# --------------------------------------------------------------------------- #
def slide_final(prs):
    s = blank(prs, dark=True)
    text(s, M, 1.15, CW, 0.3, "ИТОГ", size=12, color=ACCENT, bold=True)

    numbers = [("52", "звонка"), ("189", "задач"), ("3,6", "обещания\nна звонок"), ("119", "тестов")]
    x = M
    for value, label in numbers:
        text(s, x, 1.7, 2.9, 1.0, value, size=54, color=WHITE, bold=True)
        text(s, x, 2.75, 2.9, 0.75, label, size=14, color=RGBColor(0xC7, 0xCB, 0xE3), line=1.25)
        x += 2.95

    shape(s, MSO_SHAPE.RECTANGLE, M, 3.95, CW, 0.012, fill=RGBColor(0x3A, 0x3F, 0x63))

    text(s, M, 4.25, 8.4, 0.4, "Дальше", size=12, color=ACCENT, bold=True)
    text(s, M, 4.55, 8.8, 1.15, "Пилот на реальной нагрузке:\nточность проверки и PostgreSQL", size=24, color=WHITE, bold=True, line=1.2)

    text(s, 10.05, 4.35, 2.6, 0.3, "Репозиторий", size=11, color=MUTED, bold=True)
    text(s, 10.05, 4.65, 2.6, 1.0, "github.com/\njabkamamka/\npromise-control", size=13, color=RGBColor(0xC7, 0xCB, 0xE3), line=1.35)

    footer(s, "Кейс УралМикро · Хакатон 2026 · команда ЧИХПЫХ", dark=True)
    notes(
        s,
        "25 секунд. Итог: 52 звонка, 189 задач, 3,6 обещания на звонок, 119 тестов. Проверка исполнения "
        "по следующим звонкам уже работает. Дальше — пилот и точность. Спасибо, готовы к вопросам.",
    )


def main() -> None:
    prs = new_deck()
    slide_title(prs)
    slide_problem(prs)
    slide_solution(prs)
    slide_demo(prs)
    slide_detect(prs)
    slide_deadlines(prs)
    slide_reliability(prs)
    slide_limits(prs)
    slide_final(prs)
    prs.core_properties.title = "Сервис контроля обещаний — защита, 7 минут"
    prs.core_properties.author = "Команда ЧИХПЫХ"
    prs.core_properties.subject = "Кейс УралМикро, хакатон 2026"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"saved {OUT} ({OUT.stat().st_size} bytes, {len(prs.slides)} slides)")


if __name__ == "__main__":
    main()
