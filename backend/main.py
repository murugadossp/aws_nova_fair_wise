"""
FareWise — FastAPI Backend
Serves all three surfaces: Chrome Extension, Web App, Mobile PWA
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pathlib import Path

from logger import get_logger
from routers import travel, voice, admin
from nova.identifier import NovaIdentifier
from nova.reasoner import NovaReasoner

load_dotenv()

log = get_logger(__name__)

# ── Lifespan: warm up heavy clients once at startup ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up — warming Nova clients")
    app.state.identifier = NovaIdentifier()
    app.state.reasoner   = NovaReasoner()
    yield
    log.info("Shutting down")

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FareWise API",
    version="1.0.0",
    description="India's AI price intelligence agent — powered by Amazon Nova",
    lifespan=lifespan,
)

# ── CORS — allow Chrome Extension + localhost dev ──────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:7891",
        "http://localhost:7892",
        "http://127.0.0.1:7891",
        "http://127.0.0.1:7892",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(travel.router,   prefix="/api/travel",   tags=["Travel"])
app.include_router(voice.router,    prefix="/api/voice",    tags=["Voice"])
app.include_router(admin.router,    tags=["Admin"])

# ── Static Files: Serve logs directory ──────────────────────────────────────────
# Determine the base directory where main.py is located
base_dir = Path(__file__).parent
logs_dir = base_dir / "logs"
if logs_dir.exists():
    app.mount("/logs", StaticFiles(directory=str(logs_dir)), name="logs")

# ── Admin Dashboard ─────────────────────────────────────────────────────────────
@app.get("/admin")
async def admin_dashboard():
    """Serve the admin dashboard HTML."""
    base_dir = Path(__file__).parent
    admin_file = base_dir / "admin-backend.html"
    if admin_file.exists():
        return FileResponse(str(admin_file), media_type="text/html")
    return {"error": f"Admin dashboard not found at {admin_file}"}

# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "nova_models": ["nova-lite-v1", "nova-multimodal", "nova-pro-v1", "nova-sonic"],
    }

# ── WebSocket: streaming search results ───────────────────────────────────────
# Clients connect here and receive server-sent events as each agent completes.
# Message schema: { "type": "progress"|"result"|"done"|"error", "agent": str, "data": any }
@app.websocket("/ws/search/{task_id}")
async def ws_search(websocket: WebSocket, task_id: str):
    await websocket.accept()

    try:
        # Wait for the search payload from client
        payload = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        mode = payload.get("mode", "travel")  # default to "travel"

        if mode == "travel":
            await _run_travel_search(websocket, payload)
        else:
            await websocket.send_json({"type": "error", "message": f"Unknown mode: {mode}"})

    except asyncio.TimeoutError:
        await websocket.send_json({"type": "error", "message": "Payload timeout — send search params within 10s"})
    except WebSocketDisconnect:
        log.info("Client disconnected: task_id=%s", task_id)
    except Exception as e:
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        await websocket.close()


async def _run_travel_search(ws: WebSocket, payload: dict):
    """Orchestrate travel agents in parallel, stream progress.
    Payload fields:
      route: { from, to, date, class }  — structured route (from sidepanel form)
      query: str                         — optional raw text/voice query (planner parses it)
      cards: list[str]                   — selected bank card IDs
    """
    from agents.orchestrator import TravelOrchestrator

    route = payload.get("route", {})
    cards = payload.get("cards", [])
    query = payload.get("query")        # optional: raw natural-language input

    orchestrator = TravelOrchestrator(ws)
    await orchestrator.run(route=route, cards=cards, query=query)
