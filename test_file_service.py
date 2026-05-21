# -*- coding: utf-8 -*-

from pathlib import Path

import pytest

from app.services.file_service import (
    FileAccessDeniedError,
    FileBrowserError,
    FileBrowserService,
    FileNotFoundErrorInRoot,
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
