"""Нельзя трогать чужую задачу: ни взять, ни сменить статус."""
from __future__ import annotations

from conftest import login_admin, login_employee, make_call

CALLBACK = [{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]


def prepare(client, email="owner@example.com", name="Первый Сотрудник"):
    login_employee(client, email=email, name=name)
    client.post("/webhook/calls", json=make_call("c-owner", CALLBACK))
    task = client.get("/api/v1/tasks?limit=1").json()["items"][0]
    assert client.post(f"/api/v1/tasks/{task['id']}/take").status_code == 200
    client.post("/auth/logout", json={})
    return task


def test_second_employee_cannot_take(client):
    task = prepare(client)
    login_employee(client, email="thief@example.com", name="Второй Сотрудник")

    response = client.post(f"/api/v1/tasks/{task['id']}/take")
    assert response.status_code == 409
    assert "Первый Сотрудник" in response.json()["detail"]


def test_second_employee_cannot_change_status(client):
    task = prepare(client)
    login_employee(client, email="thief2@example.com", name="Второй Сотрудник")

    done = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})
    assert done.status_code == 403
    assert "Первый Сотрудник" in done.json()["detail"]

    back = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "created"})
    assert back.status_code == 403


def test_owner_can_close_own_task(client):
    login_employee(client, email="own@example.com", name="Своя Задача")
    client.post("/webhook/calls", json=make_call("c-own", CALLBACK))
    task = client.get("/api/v1/tasks?limit=1").json()["items"][0]
    client.post(f"/api/v1/tasks/{task['id']}/take")

    response = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})
    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_admin_can_close_foreign_task(client):
    task = prepare(client, email="owner2@example.com", name="Первый Сотрудник")
    login_admin(client)

    response = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})
    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_free_task_can_be_taken_by_anyone(client):
    login_employee(client, email="first-free@example.com")
    client.post("/webhook/calls", json=make_call("c-free", CALLBACK))
    task = client.get("/api/v1/tasks?limit=1").json()["items"][0]
    client.post("/auth/logout", json={})

    login_employee(client, email="second-free@example.com", name="Второй Свободный")
    response = client.post(f"/api/v1/tasks/{task['id']}/take")
    assert response.status_code == 200
    assert response.json()["assignee_name"] == "Второй Свободный"
