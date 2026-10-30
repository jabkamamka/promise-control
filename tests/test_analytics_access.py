"""Доступ к аналитике только администратору + аналитика по сотрудникам."""
from __future__ import annotations

from conftest import login_admin, login_employee


def test_analytics_requires_login(client):
    assert client.get("/api/v1/analytics").status_code == 401
    assert client.get("/api/v1/analytics/employees").status_code == 401
    assert client.get("/api/v1/tasks-export").status_code == 401


def test_analytics_forbidden_for_operator(client):
    login_employee(client, email="operator@example.com", name="Обычный Оператор")
    assert client.get("/api/v1/analytics").status_code == 403
    assert client.get("/api/v1/analytics/employees").status_code == 403
    assert client.get("/api/v1/tasks-export").status_code == 403


def test_analytics_page_redirects_operator(client):
    login_employee(client, email="operator2@example.com")
    response = client.get("/analytics", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?denied=analytics"


def test_admin_gets_role(client):
    employee = login_admin(client)
    assert employee["role"] == "admin"
    assert client.get("/api/v1/analytics").status_code == 200
    assert client.get("/analytics", follow_redirects=False).status_code == 200


def test_employee_analytics_structure(client, sample_calls):
    login_admin(client)
    client.post("/webhook/calls", json=sample_calls[:5])

    data = client.get("/api/v1/analytics/employees?days=30").json()
    assert data["period_days"] == 30
    assert "totals" in data and "employees" in data
    assert isinstance(data["employees"], list)
    for row in data["employees"]:
        for field in ("id", "email", "taken", "done", "overdue", "avg_close_hours", "done_share"):
            assert field in row


def test_employee_analytics_counts(client, sample_calls):
    admin = login_admin(client)
    client.post("/webhook/calls", json=sample_calls[:3])
    task = client.get("/api/v1/tasks?limit=1").json()["items"][0]
    assert client.post(f"/api/v1/tasks/{task['id']}/take").status_code == 200
    assert client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"}).status_code == 200

    data = client.get("/api/v1/analytics/employees?days=30").json()
    me = next(row for row in data["employees"] if row["id"] == admin["id"])
    assert me["taken"] >= 1
    assert me["done"] >= 1
    assert me["done_share"] > 0
    assert me["avg_close_hours"] is not None
