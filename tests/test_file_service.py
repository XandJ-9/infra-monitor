# -*- coding: utf-8 -*-

from pathlib import Path

import pytest

from app.services.file_service import (
    FileAccessDeniedError,
    FileBrowserError,
    FileBrowserService,
    FileNotFoundErrorInRoot,
    PROJECT_ROOT,
)


def make_service(root: Path, max_preview_bytes: int = 16) -> FileBrowserService:
    return FileBrowserService(
        {
            "file_browser": {
                "root": str(root),
                "max_preview_bytes": max_preview_bytes,
                "enabled": True,
            }
        }
    )


def test_list_root_and_subdirectory(tmp_path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "app.log").write_text("hello", encoding="utf-8")
    (tmp_path / "README.txt").write_text("read me", encoding="utf-8")
    service = make_service(tmp_path)

    root_listing = service.list_dir("")
    sub_listing = service.list_dir("logs")

    assert [entry["name"] for entry in root_listing["entries"]] == ["logs", "README.txt"]
    assert sub_listing["path"] == "logs"
    assert sub_listing["parent_path"] == ""
    assert sub_listing["entries"][0]["path"] == "logs/app.log"


def test_default_root_is_project_root() -> None:
    service = FileBrowserService({"file_browser": {"max_preview_bytes": 16, "enabled": True}})

    assert service.root == PROJECT_ROOT


def test_root_override_changes_browsing_boundary(tmp_path) -> None:
    configured_root = tmp_path / "configured"
    override_root = tmp_path / "override"
    configured_root.mkdir()
    override_root.mkdir()
    (configured_root / "configured.txt").write_text("configured", encoding="utf-8")
    (override_root / "override.txt").write_text("override", encoding="utf-8")

    service = FileBrowserService(
        {
            "file_browser": {
                "root": str(configured_root),
                "max_preview_bytes": 16,
                "enabled": True,
            }
        },
        root=override_root,
    )
    listing = service.list_dir("")

    assert service.root == override_root.resolve()
    assert [entry["name"] for entry in listing["entries"]] == ["override.txt"]


def test_path_traversal_is_rejected(tmp_path) -> None:
    service = make_service(tmp_path)

    with pytest.raises(FileAccessDeniedError):
        service.resolve_path("../outside.txt")


def test_absolute_path_is_rejected(tmp_path) -> None:
    service = make_service(tmp_path)

    with pytest.raises(FileAccessDeniedError):
        service.resolve_path(str(tmp_path / "README.txt"))


def test_symlink_escape_is_rejected(tmp_path) -> None:
    outside = tmp_path.parent / "outside-file-browser-target"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform")

    service = make_service(tmp_path)

    with pytest.raises(FileAccessDeniedError):
        service.resolve_path("link")


def test_symlink_escape_is_not_listed(tmp_path) -> None:
    outside = tmp_path.parent / "outside-file-browser-listing-target"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform")

    service = make_service(tmp_path)

    listing = service.list_dir("")

    assert "link" not in [entry["name"] for entry in listing["entries"]]


def test_preview_utf8_text_and_truncation(tmp_path) -> None:
    (tmp_path / "app.log").write_text("0123456789abcdef", encoding="utf-8")
    service = make_service(tmp_path, max_preview_bytes=8)

    preview = service.preview_file("app.log")

    assert preview["previewable"] is True
    assert preview["content"] == "01234567"
    assert preview["encoding"] == "utf-8"
    assert preview["truncated"] is True
    assert preview["language"] == ""


def test_preview_marks_code_languages(tmp_path) -> None:
    (tmp_path / ".bashrc").write_text("export APP_ENV=dev\n", encoding="utf-8")
    (tmp_path / "config.json").write_text('{"enabled": true}\n', encoding="utf-8")
    (tmp_path / "deploy.sh").write_text("#!/usr/bin/env bash\necho hello\n", encoding="utf-8")
    (tmp_path / "script.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    (tmp_path / "query.sql").write_text("select * from users;\n", encoding="utf-8")
    service = make_service(tmp_path)

    listing = service.list_dir("")
    bash_preview = service.preview_file("deploy.sh")
    bashrc_preview = service.preview_file(".bashrc")
    json_preview = service.preview_file("config.json")
    python_preview = service.preview_file("script.py")
    sql_preview = service.preview_file("query.sql")

    entries = {entry["name"]: entry for entry in listing["entries"]}
    assert entries[".bashrc"]["language"] == "bash"
    assert entries["config.json"]["language"] == "json"
    assert entries["deploy.sh"]["language"] == "bash"
    assert entries["script.py"]["language"] == "python"
    assert entries["query.sql"]["language"] == "sql"
    assert bash_preview["language"] == "bash"
    assert bashrc_preview["language"] == "bash"
    assert json_preview["language"] == "json"
    assert python_preview["preview_type"] == "text"
    assert python_preview["language"] == "python"
    assert sql_preview["preview_type"] == "text"
    assert sql_preview["language"] == "sql"


def test_missing_path_and_type_mismatch_errors(tmp_path) -> None:
    (tmp_path / "folder").mkdir()
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    service = make_service(tmp_path)

    with pytest.raises(FileNotFoundErrorInRoot):
        service.list_dir("missing")
    with pytest.raises(FileBrowserError, match="not a directory"):
        service.list_dir("file.txt")
    with pytest.raises(FileBrowserError, match="not a file"):
        service.preview_file("folder")


def test_binary_file_is_not_previewed(tmp_path) -> None:
    (tmp_path / "image.bin").write_bytes(b"abc\x00def")
    service = make_service(tmp_path)

    preview = service.preview_file("image.bin")

    assert preview["previewable"] is False
    assert preview["content"] == ""
    assert "Binary" in preview["error"]


def test_image_file_preview_metadata_and_validation(tmp_path) -> None:
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    service = make_service(tmp_path)

    listing = service.list_dir("")
    preview = service.preview_file("image.png")
    image_path, media_type = service.image_file("image.png")

    assert next(entry for entry in listing["entries"] if entry["name"] == "image.png")["preview_type"] == "image"
    assert preview["previewable"] is True
    assert preview["preview_type"] == "image"
    assert preview["mime_type"] == "image/png"
    assert preview["content"] == ""
    assert image_path == tmp_path / "image.png"
    assert media_type == "image/png"

    with pytest.raises(FileBrowserError, match="supported image"):
        service.image_file("note.txt")
