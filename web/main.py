"""
FastAPI + Jinja2 BFF for the asset management Web app.
Serves pages and mounts API router. Does not modify core/.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.api import get_report_merged, router as api_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app():
    from fastapi import FastAPI

    app = FastAPI(title="DPA Web")

    @app.exception_handler(404)
    async def custom_404(request: Request, exc: Exception):
        return HTMLResponse(
            content='<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><title>ページが見つかりません</title></head>'
            '<body style="font-family:sans-serif;padding:2rem;background:#0f172a;color:#e2e8f0;">'
            '<h1 style="color:#f59e0b;">404 - ページが見つかりません</h1>'
            f'<p>リクエストした URL: <code>{request.url.path}</code></p>'
            '<p><a href="/" style="color:#38bdf8;">ダッシュボードへ戻る</a> | '
            '<a href="/trade" style="color:#38bdf8;">取引</a> | '
            '<a href="/report" style="color:#38bdf8;">レポート</a></p></body></html>',
            status_code=404,
        )

    app.include_router(api_router)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    @app.get("/report", response_class=HTMLResponse)
    async def report(request: Request):
        merged = get_report_merged()
        return templates.TemplateResponse("report.html", {"request": request, **merged})

    @app.get("/analyze", response_class=HTMLResponse)
    async def analyze(request: Request):
        return templates.TemplateResponse("analyze.html", {"request": request})

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
            from web.api import _read_json, _get_positions_from_watchlist, _get_cash_yen
            pos = _get_positions_from_watchlist()
            if not isinstance(pos, dict):
                pos = {}
            last_report = _read_json(PROJECT_ROOT / "data" / "last_report.json")
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
        return templates.TemplateResponse("trade.html", {"request": request, "holdings": holdings, "cash_yen": cash_yen})

    @app.get("/watchlist", response_class=HTMLResponse)
    async def watchlist(request: Request):
        from web.api import _read_json
        wl = _read_json(PROJECT_ROOT / "data" / "watchlist.json")
        if not isinstance(wl, list):
            wl = []
        last_report = _read_json(PROJECT_ROOT / "data" / "last_report.json")
        names = (last_report or {}).get("ticker_names") or {}
        prices = (last_report or {}).get("last_prices") or {}
        list_with_names = [{"ticker": (x.get("ticker") or x.get("ticker_symbol") or ""), "status": x.get("status", "WATCHING"), "name": names.get(x.get("ticker") or x.get("ticker_symbol") or "", "-"), "price": prices.get((x.get("ticker") or x.get("ticker_symbol") or ""))} for x in wl]
        return templates.TemplateResponse("watchlist.html", {"request": request, "watchlist": list_with_names})

    @app.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        from web.api import get_settings
        data = get_settings()
        return templates.TemplateResponse("settings.html", {"request": request, **data})

    return app


app = create_app()
