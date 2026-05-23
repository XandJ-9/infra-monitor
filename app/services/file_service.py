# -*- coding: utf-8 -*-
"""Read-only filesystem browsing service."""

from __future__ import annotations

import locale
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_MIME_TYPES = {
    ".apng": "image/apng",
    ".avif": "image/avif",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
CODE_LANGUAGES = {
    ".bash": "bash",
    ".json": "json",
    ".py": "python",
    ".pyw": "python",
    ".sh": "bash",
    ".sql": "sql",
}
CODE_FILENAMES = {
    ".bashrc": "bash",
    ".bash_profile": "bash",
    ".env": "bash",
    ".profile": "bash",
}


class FileBrowserError(Exception):
    """Base exception for file browser failures."""

    status_code = 400


class FileBrowserDisabledError(FileBrowserError):
    """Raised when the file browser is disabled by config."""

    status_code = 404


class FileAccessDeniedError(FileBrowserError):
    """Raised when a path resolves outside the configured root."""

    status_code = 403


class FileNotFoundErrorInRoot(FileBrowserError):
    """Raised when a path inside root does not exist."""

    status_code = 404


class FileBrowserService:
    """Safe, read-only access to a configured filesystem root."""

    def __init__(self, config: dict[str, Any] | None = None, root: str | Path | None = None) -> None:
        cfg = config if config is not None else load_config()
        browser_cfg = cfg.get("file_browser", {})
        self.enabled = bool(browser_cfg.get("enabled", True))
        self.max_preview_bytes = int(browser_cfg.get("max_preview_bytes", 262144))
        configured_root = Path(str(root or browser_cfg.get("root", "."))).expanduser()
        if not configured_root.is_absolute():
            configured_root = PROJECT_ROOT / configured_root
        self.root = configured_root.resolve()

    def list_dir(self, relative_path: str = "") -> dict[str, Any]:
        """Return directory metadata and children."""
        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundErrorInRoot("Path does not exist")
        if not target.is_dir():
            raise FileBrowserError("Path is not a directory")

        entries = []
        for child in target.iterdir():
            try:
                child.resolve().relative_to(self.root)
                stat = child.stat()
                entries.append(self._entry(child, stat))
            except (OSError, ValueError):
                continue

        entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
        current_path = self._relative(target)
        return {
            "path": current_path,
            "parent_path": self._parent_path(current_path),
            "entries": entries,
            "root": str(self.root),
        }

    def preview_file(self, relative_path: str) -> dict[str, Any]:
        """Return a bounded text preview and metadata for a file."""
        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundErrorInRoot("Path does not exist")
        if not target.is_file():
            raise FileBrowserError("Path is not a file")

        stat = target.stat()
        image_mime_type = self.image_mime_type(target)
        if image_mime_type:
            return self._preview_payload(
                target,
                stat,
                content="",
                encoding="",
                truncated=False,
                previewable=True,
                error="",
                preview_type="image",
                mime_type=image_mime_type,
            )

        read_limit = max(0, self.max_preview_bytes)
        with target.open("rb") as file:
            raw = file.read(read_limit + 1)

        truncated = len(raw) > read_limit or stat.st_size > read_limit
        sample = raw[:read_limit]
        if b"\x00" in sample:
            return self._preview_payload(
                target,
                stat,
                content="",
                encoding="",
                truncated=truncated,
                previewable=False,
                error="Binary file preview is not supported.",
                preview_type="unsupported",
                mime_type="",
            )

        encoding = "utf-8"
        try:
            content = sample.decode(encoding)
        except UnicodeDecodeError:
            encoding = locale.getpreferredencoding(False) or "utf-8"
            content = sample.decode(encoding, errors="replace")

        return self._preview_payload(
            target,
            stat,
            content=content,
            encoding=encoding,
            truncated=truncated,
            previewable=True,
            error="",
            preview_type="text",
            mime_type="text/plain",
            language=self.code_language(target),
        )

    def image_file(self, relative_path: str) -> tuple[Path, str]:
        """Return a validated image file path and media type."""
        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundErrorInRoot("Path does not exist")
        if not target.is_file():
            raise FileBrowserError("Path is not a file")

        mime_type = self.image_mime_type(target)
        if not mime_type:
            raise FileBrowserError("Path is not a supported image file")
        return target, mime_type

    @staticmethod
    def image_mime_type(path: Path) -> str:
        """Return the browser-safe image media type for a supported extension."""
        return IMAGE_MIME_TYPES.get(path.suffix.lower(), "")

    @staticmethod
    def code_language(path: Path) -> str:
        """Return the supported syntax language for code previews."""
        return CODE_FILENAMES.get(path.name.lower(), CODE_LANGUAGES.get(path.suffix.lower(), ""))

    def resolve_path(self, relative_path: str = "") -> Path:
        """Resolve a user path and ensure it stays within root."""
        if not self.enabled:
            raise FileBrowserDisabledError("File browser is disabled")

        raw = (relative_path or "").strip()
        candidate_path = Path(raw)
        if candidate_path.is_absolute():
            raise FileAccessDeniedError("Absolute paths are not allowed")

        candidate = (self.root / candidate_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise FileAccessDeniedError("Path escapes configured root") from exc
        return candidate

    def _entry(self, path: Path, stat_result: Any) -> dict[str, Any]:
        is_dir = path.is_dir()
        return {
            "name": path.name,
            "path": self._relative(path),
            "is_dir": is_dir,
            "size": None if is_dir else stat_result.st_size,
            "modified": self._format_time(stat_result.st_mtime),
            "extension": "" if is_dir else path.suffix.lower(),
            "preview_type": "" if is_dir else ("image" if self.image_mime_type(path) else "text"),
            "language": "" if is_dir else self.code_language(path),
        }

    def _preview_payload(
        self,
        path: Path,
        stat_result: Any,
        *,
        content: str,
        encoding: str,
        truncated: bool,
        previewable: bool,
        error: str,
        preview_type: str = "text",
        mime_type: str = "",
        language: str = "",
    ) -> dict[str, Any]:
        return {
            "path": self._relative(path),
            "name": path.name,
            "size": stat_result.st_size,
            "modified": self._format_time(stat_result.st_mtime),
            "content": content,
            "encoding": encoding,
            "truncated": truncated,
            "previewable": previewable,
            "error": error,
            "preview_type": preview_type,
            "mime_type": mime_type,
            "language": language,
        }

    def _relative(self, path: Path) -> str:
        if path == self.root:
            return ""
        return path.relative_to(self.root).as_posix()

    @staticmethod
    def _format_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _parent_path(relative_path: str) -> str | None:
        if not relative_path:
            return None
        parent = Path(relative_path).parent.as_posix()
        return "" if parent == "." else parent
