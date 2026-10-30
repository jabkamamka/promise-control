"""Отправка писем сотрудникам.

Два транспорта:

* ``smtp`` — обычная отправка через SMTP-сервер (``smtplib`` из стандартной библиотеки);
* ``file`` — письмо складывается в ``data/outbox`` как ``.eml``. Это не заглушка «в никуда»:
  файл можно открыть почтовым клиентом, а в консоли видно строку об отправке.
  Так сервис работает на машине без доступа к внешнему SMTP.

Режим ``auto`` (по умолчанию) выбирает SMTP, если задан ``SMTP_HOST``, иначе файл.
Ошибка отправки никогда не ломает запрос: возвращается статус ``failed`` с текстом причины.
"""
from __future__ import annotations

import datetime as dt
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import NamedTuple

from ..config import settings


class MailResult(NamedTuple):
    status: str  # sent | file | failed | disabled
    detail: str = ""


#: Настройки популярных почт: хост, порт и тип шифрования.
#: Если оператор указал только логин и пароль, остальное подставится по домену адреса.
PRESETS: dict[str, tuple[str, int, str]] = {
    "yandex.ru": ("smtp.yandex.ru", 465, "ssl"),
    "yandex.com": ("smtp.yandex.ru", 465, "ssl"),
    "ya.ru": ("smtp.yandex.ru", 465, "ssl"),
    "gmail.com": ("smtp.gmail.com", 587, "starttls"),
    "googlemail.com": ("smtp.gmail.com", 587, "starttls"),
    "mail.ru": ("smtp.mail.ru", 465, "ssl"),
    "inbox.ru": ("smtp.mail.ru", 465, "ssl"),
    "list.ru": ("smtp.mail.ru", 465, "ssl"),
    "bk.ru": ("smtp.mail.ru", 465, "ssl"),
    "outlook.com": ("smtp.office365.com", 587, "starttls"),
    "hotmail.com": ("smtp.office365.com", 587, "starttls"),
    "live.com": ("smtp.office365.com", 587, "starttls"),
    # бесплатные релеи: 300 писем в день и 1000 в месяц
    "brevo": ("smtp-relay.brevo.com", 587, "starttls"),
    "smtp2go": ("mail.smtp2go.com", 587, "starttls"),
}


def _account_domain() -> str:
    """Домен ящика: из SMTP_USER, иначе из EMAIL_FROM."""
    for raw in (settings.smtp_user, _bare_address(settings.email_from)):
        if raw and "@" in raw:
            return raw.rsplit("@", 1)[1].strip().lower()
    return ""


def smtp_config() -> tuple[str, int, str]:
    """Возвращает (host, port, security). Пустой host — SMTP не настроен."""
    host = settings.smtp_host.strip()
    security = (settings.smtp_security or "auto").lower()

    if host:
        port = settings.smtp_port or (465 if security == "ssl" else 587)
        if security == "auto":
            security = "ssl" if port == 465 else "starttls"
        return host, port, security

    preset = PRESETS.get(_account_domain())
    if not preset:
        return "", 0, security
    preset_host, preset_port, _preset_security = preset
    port = settings.smtp_port or preset_port
    if security == "auto":
        security = "ssl" if port == 465 else "starttls"
    return preset_host, port, security


def transport() -> str:
    """Какой транспорт реально будет использован."""
    if not settings.email_enabled:
        return "disabled"
    mode = (settings.email_transport or "auto").lower()
    if mode == "file":
        return "file"
    host, _port, _security = smtp_config()
    if mode == "smtp":
        return "smtp" if host else "disabled"
    return "smtp" if host else "file"


def describe() -> dict:
    """Короткое описание режима — для интерфейса и /health."""
    mode = transport()
    host, port, security = smtp_config()
    return {
        "enabled": settings.email_enabled,
        "transport": mode,
        "from": settings.email_from,
        "smtp_host": host or None,
        "smtp_port": port or None,
        "smtp_security": security or None,
        "smtp_user": settings.smtp_user or None,
        "redirect_to": settings.email_redirect_to or None,
    }


def _build_message(to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="promise-control.local")
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def _write_to_outbox(message: EmailMessage, to: str) -> str:
    outbox = Path(settings.email_outbox)
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    safe = "".join(ch if ch.isalnum() or ch in "._@-" else "_" for ch in to)
    path = outbox / f"{stamp}-{safe}.eml"
    path.write_bytes(bytes(message))
    return str(path)


def _should_redirect(recipient: str, redirect: str, domains: str) -> bool:
    """Переадресовывать ли письмо.

    Если список доменов задан, переадресация работает только для них:
    реальные сотрудники получают письма на свои ящики, а условные
    адреса вроде maria@example.com — на демо-ящик.
    """
    if not redirect:
        return False
    allowed = {item.strip().lower() for item in (domains or "").split(",") if item.strip()}
    if not allowed:
        return True
    domain = recipient.rsplit("@", 1)[-1].strip().lower() if "@" in recipient else ""
    return domain in allowed


def send(to: str, subject: str, text: str, html: str | None = None) -> MailResult:
    """Отправляет письмо. Исключений не бросает."""
    mode = transport()
    if mode == "disabled":
        return MailResult("disabled", "отправка почты выключена")

    original = (to or "").strip()
    if not original:
        return MailResult("failed", "у сотрудника не указан email")

    recipient = original
    note = ""
    if _should_redirect(original, settings.email_redirect_to, settings.email_redirect_domains):
        # Демо: письма на условные адреса идут на один реальный ящик.
        recipient = settings.email_redirect_to
        note = f"\n\n—\nДемо-переадресация: письмо предназначалось {original}"

    message = _build_message(recipient, subject, text + note, html)

    if mode == "file":
        try:
            path = _write_to_outbox(message, recipient)
        except OSError as exc:
            return MailResult("failed", f"не удалось записать письмо: {exc}")
        return MailResult("file", path)

    return _send_smtp(message, recipient)


def _send_smtp(message: EmailMessage, recipient: str) -> MailResult:
    host, port, security = smtp_config()
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=settings.smtp_timeout, context=context
            )
        else:
            server = smtplib.SMTP(host, port, timeout=settings.smtp_timeout)
        with server:
            server.ehlo()
            if security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message, from_addr=_bare_address(settings.email_from), to_addrs=[recipient])
    except smtplib.SMTPAuthenticationError:
        return MailResult(
            "failed", "логин или пароль приложения не подошли — проверьте SMTP_USER и SMTP_PASSWORD"
        )
    except (smtplib.SMTPException, OSError) as exc:
        return MailResult("failed", f"SMTP {host}:{port}: {exc}")
    return MailResult("sent", f"SMTP {host}:{port} ({security})")


def _bare_address(value: str) -> str:
    """«Имя <mail@host>» -> «mail@host»."""
    if "<" in value and ">" in value:
        return value[value.rindex("<") + 1 : value.rindex(">")].strip()
    return value.strip()


def format_from(name: str = "Контроль обещаний") -> str:
    return formataddr((name, _bare_address(settings.email_from)))


def send_confirm_link(email: str, link: str, hours: int) -> MailResult:
    """Письмо с подтверждением почты: без него вход в сервис закрыт."""
    text = (
        "Здравствуйте!\n\n"
        "Вы зарегистрировались в сервисе контроля обещаний. Остался один шаг —\n"
        "подтвердить почту, иначе вход будет закрыт.\n\n"
        f"Подтвердить: {link}\n\n"
        f"Ссылка действует {hours} ч и работает один раз.\n"
        "Если регистрировались не вы — просто проигнорируйте письмо.\n\n"
        "— Сервис контроля обещаний, UralMicro"
    )
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:24px;background:#f2eee5;
 font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#16150f">
  <div style="max-width:520px;margin:0 auto;background:#fffdf8;border:1px solid #e2dbcc;
   border-radius:14px;padding:24px">
    <p style="margin:0 0 16px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#8a8474">
      Контроль обещаний · UralMicro</p>
    <p style="margin:0 0 8px;font-size:17px;font-weight:600">Подтвердите почту</p>
    <p style="margin:0 0 18px;color:#3d3a32;line-height:1.5">
      Без подтверждения вход в панель закрыт. Это займёт один клик.</p>
    <p style="margin:0 0 18px"><a href="{link}"
      style="display:inline-block;padding:12px 20px;background:#16150f;color:#fffdf8;
      border-radius:10px;text-decoration:none">Подтвердить почту</a></p>
    <p style="margin:0;color:#8a8474;font-size:12.5px;line-height:1.45">
      Ссылка действует {hours} ч и работает один раз. Если регистрировались не вы — проигнорируйте письмо.</p>
  </div>
</body></html>"""
    return send(email, "Подтвердите почту — Контроль обещаний", text, html=html)


def send_login_link(email: str, link: str, code: str, minutes: int) -> MailResult:
    """Письмо со ссылкой и кодом для входа без пароля."""
    text = (
        "Здравствуйте!\n\n"
        "Чтобы войти в сервис контроля обещаний, откройте ссылку:\n"
        f"{link}\n\n"
        f"Или введите код вручную: {code}\n\n"
        f"Ссылка и код действуют {minutes} минут и работают один раз.\n"
        "Если вы не запрашивали вход — просто проигнорируйте письмо.\n\n"
        "— Сервис контроля обещаний, UralMicro"
    )
    html = f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:24px;background:#f2eee5;
 font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#16150f">
  <div style="max-width:520px;margin:0 auto;background:#fffdf8;border:1px solid #e2dbcc;
   border-radius:14px;padding:24px">
    <p style="margin:0 0 16px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#8a8474">
      Контроль обещаний · UralMicro</p>
    <p style="margin:0 0 8px;font-size:17px;font-weight:600">Вход по ссылке</p>
    <p style="margin:0 0 18px;color:#3d3a32;line-height:1.5">
      Нажмите кнопку — и попадёте в панель. Пароль не нужен.</p>
    <p style="margin:0 0 18px"><a href="{link}"
      style="display:inline-block;padding:12px 20px;background:#16150f;color:#fffdf8;
      border-radius:10px;text-decoration:none">Войти в сервис</a></p>
    <p style="margin:0 0 6px;color:#6b6659;font-size:13px">Или введите код вручную:</p>
    <p style="margin:0 0 18px;font-family:ui-monospace,Menlo,Consolas,monospace;
     font-size:26px;letter-spacing:.18em">{code}</p>
    <p style="margin:0;color:#8a8474;font-size:12.5px;line-height:1.45">
      Ссылка и код действуют {minutes} минут и работают один раз. Если вы не запрашивали вход —
      проигнорируйте письмо.</p>
  </div>
</body></html>"""
    return send(email, "Вход в «Контроль обещаний»", text, html=html)
