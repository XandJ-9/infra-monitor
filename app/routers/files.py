# -*- coding: utf-8 -*-
"""Read-only online file browser routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.services.file_service import FileBrowserError, FileBrowserService

router = APIRouter(prefix="/files", tags=["Files"])


def _service_response(call):
    try:
        return call()
    except FileBrowserError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/", response_class=HTMLResponse)
async def files_page(request: Request, path: str = Query(default="")):
    """Render the read-only file browser page."""
    service = FileBrowserService()
    error = ""
    listing = {"path": path, "parent_path": None, "entries": [], "root": str(service.root)}
    try:
        listing = service.list_dir(path)
    except FileBrowserError as exc:
        error = str(exc)
    except OSError as exc:
        error = str(exc)

    return request.app.state.templates.TemplateResponse(
        request,
        "files.html",
        {
            "listing": listing,
            "error": error,
        },
    )


@router.get("/api/list")
async def list_files(path: str = Query(default="")):
    """Return directory entries under the configured root."""
    service = FileBrowserService()
    return _service_response(lambda: service.list_dir(path))


@router.get("/api/preview")
async def preview_file(path: str = Query(default="")):
    """Return a bounded text preview for a file."""
    service = FileBrowserService()
    return _service_response(lambda: service.preview_file(path))
