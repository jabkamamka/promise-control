"""Тесты переадресации писем по домену и фактического адреса доставки."""
from __future__ import annotations

import dataclasses

import pytest

from app.services import mailer
from app.services.mailer import _should_redirect


def test_redirect_off_when_empty():
    assert _should_redirect("maria@example.com", "", "") is False


def test_redirect_all_when_domains_not_set():
    assert _should_redirect("maria@example.com", "demo@yandex.ru", "") is True
    assert _should_redirect("boss@uralmicro.ru", "demo@yandex.ru", "") is True


def test_redirect_only_listed_domains():
    domains = "example.com, example.org"
    assert _should_redirect("maria@example.com", "demo@yandex.ru", domains) is True
    assert _should_redirect("PETR@Example.org", "demo@yandex.ru", domains) is True
    assert _should_redirect("boss@uralmicro.ru", "demo@yandex.ru", domains) is False
    assert _should_redirect("bn.4a@yandex.ru", "demo@yandex.ru", domains) is False


def test_redirect_ignores_whitespace_and_case():
    assert _should_redirect("a@example.com", "demo@yandex.ru", " EXample.com , ") is True


@pytest.fixture()
def redirect_settings(monkeypatch):
    """Демо-переадресация на демо-ящик, только для example.com."""
    replaced = dataclasses.replace(
        mailer.settings,
        email_transport="file",
        email_enabled=True,
        email_redirect_to="bn.4a@yandex.ru",
        email_redirect_domains="example.com",
    )
    monkeypatch.setattr(mailer, "settings", replaced)
    return replaced


def test_send_reports_real_recipient_when_redirect_does_not_apply(redirect_settings):
    """Реальный адрес не из списка демо-доменов: письмо идёт туда и так и отчитывается."""
    result = mailer.send("wekimu@vgmale.com", "Тема", "Текст")

    assert result.status == "file"
    assert result.recipient == "wekimu@vgmale.com"
    assert result.redirected is False


def test_send_reports_redirect_target_when_redirect_applies(redirect_settings):
    result = mailer.send("maria@example.com", "Тема", "Текст")

    assert result.status == "file"
    assert result.recipient == "bn.4a@yandex.ru"
    assert result.redirected is True
