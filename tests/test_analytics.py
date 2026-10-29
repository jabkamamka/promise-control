"""Аналитика и выгрузка CSV: новые методы, существующие не ломают."""
from __future__ import annotations

import csv
import io


def _seed(client, sample_calls):
    client.post("/webhook/calls", json=sample_calls[:12])


def test_analytics_structure(client, sample_calls):
    _seed(client, sample_calls)
    data = client.get("/api/v1/analytics?days=14").json()

    assert data["period_days"] == 14
    assert data["timezone"] == "Asia/Yekaterinburg"
    assert len(data["series"]) == 14
    assert data["series"] == sorted(data["series"], key=lambda d: d["date"])

    totals = data["totals"]
    for key in ("calls", "tasks", "closed", "overdue", "not_fulfilled", "open", "due_today"):
        assert key in totals
        assert totals[key] >= 0

    assert sum(item["count"] for item in data["by_type"]) == totals["tasks"]
    assert sum(data["by_status"].values()) == totals["tasks"]
    assert sum(data["by_verification"].values()) == totals["tasks"]


def test_analytics_matches_stats(client, sample_calls):
    _seed(client, sample_calls)
    analytics = client.get("/api/v1/analytics").json()
    stats = client.get("/api/v1/stats").json()

    assert analytics["totals"]["tasks"] == stats["tasks_total"]
    assert analytics["totals"]["calls"] == stats["calls_total"]
    assert analytics["totals"]["overdue"] == stats["overdue"]
    assert analytics["totals"]["not_fulfilled"] == stats["not_fulfilled"]
    assert analytics["by_status"] == stats["by_status"]
    assert analytics["by_verification"] == stats["by_verification"]


def test_analytics_period_validation(client):
    assert client.get("/api/v1/analytics?days=0").status_code == 422
    assert client.get("/api/v1/analytics?days=91").status_code == 422
    assert client.get("/api/v1/analytics?days=7").json()["period_days"] == 7


def test_analytics_operators_and_close_time(client, sample_calls):
    _seed(client, sample_calls)

    task = client.get("/api/v1/tasks?limit=1").json()["items"][0]
    client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})

    data = client.get("/api/v1/analytics").json()
    assert data["close_time"]["closed_count"] == 1
    assert data["close_time"]["median_hours"] is not None
    assert any(op["done"] >= 1 for op in data["operators"])


def test_csv_export_shape(client, sample_calls):
    _seed(client, sample_calls)
    total = client.get("/api/v1/tasks?limit=1").json()["total"]

    response = client.get("/api/v1/tasks-export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    body = response.content.decode("utf-8")
    assert body.startswith("\ufeff")

    rows = list(csv.reader(io.StringIO(body.lstrip("\ufeff")), delimiter=";"))
    assert rows[0][0] == "ID задачи"
    assert len(rows) == total + 1
    assert all(len(row) == len(rows[0]) for row in rows)


def test_csv_export_respects_filters(client, sample_calls):
    _seed(client, sample_calls)

    by_type = client.get("/api/v1/tasks?type=documents&limit=1").json()["total"]
    exported = client.get("/api/v1/tasks-export?type=documents").content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(exported.lstrip("\ufeff")), delimiter=";"))
    assert len(rows) - 1 == by_type

    by_operator = client.get("/api/v1/tasks?operator_id=7&limit=1").json()["total"]
    exported_operator = client.get("/api/v1/tasks-export?operator_id=7").content.decode("utf-8")
    rows_operator = list(csv.reader(io.StringIO(exported_operator.lstrip("\ufeff")), delimiter=";"))
    assert len(rows_operator) - 1 == by_operator


def test_csv_handles_quotes_and_semicolons(client):
    call = {
        "id": "csv-escape-1",
        "operator_id": 1,
        "client_phone": "+79001234567",
        "started_at": "2026-10-29T09:00:00Z",
        "ended_at": "2026-10-29T09:05:00Z",
        "transcript": [
            {"speaker": "operator", "text": 'Перезвоню завтра; уточню "детали" и отправлю счёт.'},
        ],
    }
    client.post("/webhook/calls", json=[call])

    exported = client.get("/api/v1/tasks-export?call_id=csv-escape-1").content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(exported.lstrip("\ufeff")), delimiter=";"))
    assert len(rows) == 2
    assert all(len(row) == len(rows[0]) for row in rows)
    assert any("Перезвоню" in cell for row in rows[1:] for cell in row)
