# -*- coding: utf-8 -*-

import json

from fastapi.testclient import TestClient

import app.config as config
from app.main import app


def test_files_page_and_apis(tmp_path, monkeypatch) -> None:
    (tmp_path / "subdir").mkdir()
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"file_browser": {"root": str(tmp_path), "max_preview_bytes": 32}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    client = TestClient(app)

    page = client.get("/files/")
    listing = client.get("/files/api/list")
    preview = client.get("/files/api/preview", params={"path": "hello.txt"})
    denied = client.get("/files/api/list", params={"path": "../"})

    assert page.status_code == 200
    assert "文件浏览器" in page.text
    assert listing.status_code == 200
    assert [entry["name"] for entry in listing.json()["entries"]] == ["subdir", "config.json", "hello.txt"]
    assert preview.status_code == 200
    assert preview.json()["content"] == "hello"
    assert denied.status_code == 403


def test_files_api_error_statuses(tmp_path, monkeypatch) -> None:
    (tmp_path / "folder").mkdir()
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps({"file_browser": {"root": str(tmp_path), "max_preview_bytes": 32}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_path)
    client = TestClient(app)

    missing = client.get("/files/api/list", params={"path": "missing"})
    file_as_directory = client.get("/files/api/list", params={"path": "hello.txt"})
    directory_as_file = client.get("/files/api/preview", params={"path": "folder"})
    absolute = client.get("/files/api/preview", params={"path": str(tmp_path / "hello.txt")})

    assert missing.status_code == 404
    assert file_as_directory.status_code == 400
    assert directory_as_file.status_code == 400
    assert absolute.status_code == 403
