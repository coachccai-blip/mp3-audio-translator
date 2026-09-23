"""Doublr — application FastAPI (API REST + WebSocket de progression)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api import projects, settings as settings_api, voices
from .config import get_settings
from .models import get_engine
from .services.jobs import manager

@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_engine()
    yield


app = FastAPI(title="Doublr", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects.router)
app.include_router(voices.router)
app.include_router(settings_api.router)


@app.middleware("http")
async def private_network_access(request, call_next):
    """Autorise une page HTTPS publique (GitHub Pages) à joindre ce serveur local (Private Network Access)."""
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/api/health")
def health():
    return {"ok": True, "app": "doublr", "version": app.version}


@app.websocket("/api/ws/jobs/{job_id}")
async def job_ws(ws: WebSocket, job_id: str):
    await ws.accept()
    try:
        while True:
            state = manager.get(job_id)
            if state is None:
                await ws.send_json({"error": "Job introuvable"})
                break
            snap = state.snapshot()
            await ws.send_json(snap)
            if snap["status"] in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(0.4)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass
