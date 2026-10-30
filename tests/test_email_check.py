"""Кнопка «Проверить почту»: отчёт о том, куда письмо ушло на самом деле."""
from __future__ import annotations

import dataclasses

from app.services import mailer
from conftest import login_employee


def test_test_email_reports_own_address(client):
    """Демо-переадресация не настроена — письмо идёт на адрес сотрудника."""
    login_employee(client, email="wekimu@vgmale.com")

    body = client.post("/api/v1/notifications/test").json()

    assert body["status"] == "file"
    assert body["to"] == "wekimu@vgmale.com"
    assert body["sent_to"] == "wekimu@vgmale.com"
    assert body["redirected"] is False


def test_test_email_marks_demo_redirect(client, monkeypatch):
    """Сработала переадресация — панель должна сказать об этом прямо."""
    replaced = dataclasses.replace(
        mailer.settings,
        email_transport="file",
        email_enabled=True,
        email_redirect_to="bn.4a@yandex.ru",
        email_redirect_domains="example.com",
    )
    monkeypatch.setattr(mailer, "settings", replaced)
    login_employee(client, email="maria@example.com")

    body = client.post("/api/v1/notifications/test").json()

    assert body["to"] == "maria@example.com"
    assert body["sent_to"] == "bn.4a@yandex.ru"
    assert body["redirected"] is True


def test_test_email_requires_login(client):
    response = client.post("/api/v1/notifications/test")

    assert response.status_code == 401
