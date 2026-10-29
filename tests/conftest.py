import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Поднимает приложение на временной базе, чтобы тесты не трогали рабочие данные."""
    from fastapi.testclient import TestClient

    from app import config, db

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
