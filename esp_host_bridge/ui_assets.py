from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Tuple


_HOST_UI_JS_PATH = Path(__file__).resolve().parent / "host_ui.js"
_HOST_UI_CSS_PATH = Path(__file__).resolve().parent / "host_ui.css"
_HOST_UI_JS_CACHE: Optional[str] = None
_HOST_UI_CSS_CACHE: Optional[str] = None


def load_host_ui_js() -> str:
    global _HOST_UI_JS_CACHE
    if _HOST_UI_JS_CACHE is None:
        _HOST_UI_JS_CACHE = _HOST_UI_JS_PATH.read_text(encoding="utf-8", errors="ignore")
    return _HOST_UI_JS_CACHE


def load_host_ui_css() -> str:
    global _HOST_UI_CSS_CACHE
    if _HOST_UI_CSS_CACHE is None:
        _HOST_UI_CSS_CACHE = _HOST_UI_CSS_PATH.read_text(encoding="utf-8", errors="ignore")
    return _HOST_UI_CSS_CACHE


def host_static_asset(asset_name: str) -> Tuple[Optional[str], Optional[str]]:
    name = str(asset_name or "").strip().lower()
    if name == "host_ui.js":
        return load_host_ui_js(), "application/javascript"
    if name == "host_ui.css":
        return load_host_ui_css(), "text/css"
    return None, None


def register_host_static_routes(app: Any, *, route_prefix: str = "/static/host") -> None:
    endpoint = "host_static_asset"
    if endpoint in getattr(app, "view_functions", {}):
        return

    @app.get(f"{route_prefix}/<path:asset_name>", endpoint=endpoint)
    def host_static_asset_route(asset_name: str) -> Any:
        from flask import Response

        payload, mimetype = host_static_asset(asset_name)
        if payload is None or mimetype is None:
            return Response("Not Found", status=404, mimetype="text/plain")
        resp = Response(payload, status=200, mimetype=mimetype)
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp
