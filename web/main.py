"""
FastAPI + Jinja2 BFF for the asset management Web app.
Serves pages and mounts API router. Does not modify core/.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.api import get_report_merged, router as api_router

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def create_app():
    from fastapi import FastAPI
    app = FastAPI(title="DPA Web")
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

    @app.get("/positions", response_class=HTMLResponse)
    async def positions(request: Request):
        from web.api import _read_json
        pos = _read_json(PROJECT_ROOT / "data" / "positions.json") or {}
        last_report = _read_json(PROJECT_ROOT / "data" / "last_report.json")
        names = (last_report or {}).get("ticker_names") or {}
        last_prices = (last_report or {}).get("last_prices") or {}
        positions_list = [
            {
                "ticker": t,
                "name": names.get(t, "-"),
                "shares": (e.get("shares") or e.get("shares_held")) or 0,
                "avg_price": e.get("avg_price"),
                "last_price": last_prices.get(t),
            }
            for t, e in pos.items()
        ]
        return templates.TemplateResponse("positions.html", {"request": request, "positions": positions_list})

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
        from web.api import _read_json
        state = _read_json(PROJECT_ROOT / "portfolio_state.json") or {}
        cash = state.get("cash_yen")
        return templates.TemplateResponse("settings.html", {"request": request, "cash_yen": cash})
    return app


app = create_app()
