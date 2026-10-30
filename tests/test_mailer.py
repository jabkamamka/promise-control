"""Тесты переадресации писем по домену."""
from __future__ import annotations

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
