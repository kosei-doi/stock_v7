"""
FastAPI + Jinja2 BFF for the asset management Web app.
Serves pages and mounts API router. Does not modify core/.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from web.api import get_report_merged, limiter, router as api_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_dpa_api_key = os.environ.get("DPA_API_KEY") or ""
templates.env.globals["dpa_api_key"] = _dpa_api_key
templates.env.globals["dpa_api_key_json"] = json.dumps(_dpa_api_key)


def create_app():
    from fastapi import FastAPI

    is_production = os.environ.get("DPA_ENV", "").lower() == "production"
    app = FastAPI(
        title="DPA Web",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(404)
    async def custom_404(request: Request, exc: Exception):
        safe_path = html.escape(request.url.path, quote=True)
        return HTMLResponse(
            content='<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>ページが見つかりません</title></head>'
            '<body style="font-family:sans-serif;padding:2rem;background:#0f172a;color:#e2e8f0;">'
            '<h1 style="color:#f59e0b;">404 - ページが見つかりません</h1>'
            f'<p>リクエストした URL: <code>{safe_path}</code></p>'
            '<p><a href="/" style="color:#38bdf8;">ダッシュボードへ戻る</a> | '
            '<a href="/trade" style="color:#38bdf8;">取引</a> | '
            '<a href="/report" style="color:#38bdf8;">レポート</a></p></body></html>',
            status_code=404,
        )

    app.include_router(api_router)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", {"request": request})

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse(request, "dashboard.html", {"request": request})

    @app.get("/report", response_class=HTMLResponse)
    async def report(request: Request):
        merged = get_report_merged()
        return templates.TemplateResponse(request, "report.html", {"request": request, **merged})

    @app.get("/analyze", response_class=HTMLResponse)
    async def analyze(request: Request):
        from web.api import build_watchlist_analysis_index

        return templates.TemplateResponse(
            request,
            "analyze.html",
            {
                "request": request,
                "analysis_index_items": build_watchlist_analysis_index(),
            },
        )

    @app.get("/trade/")
    @app.get("/Trade", include_in_schema=False)
    @app.get("/TRADE", include_in_schema=False)
    async def trade_redirect():
        return RedirectResponse(url="/trade", status_code=307)

    @app.get("/trade", response_class=HTMLResponse)
    async def trade(request: Request):
        holdings = []
        cash_yen = 0
        try:
            from core.persistence import get_persistence
            from web.api import _get_positions_from_watchlist, _get_cash_yen
            pos = _get_positions_from_watchlist()
            if not isinstance(pos, dict):
                pos = {}
            last_report = get_persistence().daily_report.get_last() or {}
            names = (last_report or {}).get("ticker_names") or {}
            last_prices = (last_report or {}).get("last_prices") or {}
            holdings = [
                {
                    "ticker": t,
                    "name": names.get(t, "-"),
                    "shares": (e.get("shares") or e.get("shares_held")) or 0,
                    "avg_price": e.get("avg_price"),
                    "last_price": last_prices.get(t),
                }
                for t, e in pos.items()
            ]
            cash_yen = _get_cash_yen()
        except Exception:
            import traceback
            traceback.print_exc()
        return templates.TemplateResponse(
            request, "trade.html", {"request": request, "holdings": holdings, "cash_yen": cash_yen}
        )

    @app.get("/watchlist", response_class=HTMLResponse)
    async def watchlist(request: Request):
        from core.persistence import get_persistence
        wl = get_persistence().watchlist.load_all()
        last_report = get_persistence().daily_report.get_last() or {}
        names = (last_report or {}).get("ticker_names") or {}
        prices = (last_report or {}).get("last_prices") or {}
        list_with_names = [{"ticker": (x.get("ticker") or x.get("ticker_symbol") or ""), "status": x.get("status", "WATCHING"), "name": names.get(x.get("ticker") or x.get("ticker_symbol") or "", "-"), "price": prices.get((x.get("ticker") or x.get("ticker_symbol") or ""))} for x in wl]
        return templates.TemplateResponse(
            request, "watchlist.html", {"request": request, "watchlist": list_with_names}
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        from web.api import get_settings
        data = get_settings()
        return templates.TemplateResponse(request, "settings.html", {"request": request, **data})

    return app


app = create_app()
