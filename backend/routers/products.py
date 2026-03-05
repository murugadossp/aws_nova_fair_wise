"""Products router — REST fallback for non-WebSocket clients."""

import base64
import os
import sys
import uuid
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

log = get_logger(__name__)
router = APIRouter()


class ProductTextRequest(BaseModel):
    query: str
    cards: list[str] = []


@router.post("/identify-image")
async def identify_image(
    request: Request,
    image: UploadFile = File(...),
    cards: str = Form(default=""),
):
    """Identify product from uploaded screenshot (REST endpoint)."""
    image_bytes = await image.read()
    image_b64   = base64.b64encode(image_bytes).decode()
    card_list   = [c.strip() for c in cards.split(",") if c.strip()]
    log.info("identify_image: filename='%s' size=%d bytes cards=%s",
             image.filename, len(image_bytes), card_list)

    identifier = request.app.state.identifier
    result = await identifier.identify_from_image(image_b64)

    if not result.get("success"):
        log.warning("identify_image failed: %s", result.get("error"))
        raise HTTPException(status_code=422, detail=result.get("error", "Identification failed"))

    log.info("identify_image result: product='%s' confidence=%.2f",
             result.get("product_name"), result.get("confidence", 0))
    return result


@router.post("/search-text")
async def search_text(body: ProductTextRequest, request: Request):
    """Identify product from text query (REST endpoint)."""
    log.info("search_text: query='%s' cards=%s", body.query, body.cards)
    identifier = request.app.state.identifier
    result = await identifier.identify_from_text(body.query)
    log.info("search_text result: search_query='%s'", result.get("search_query"))
    return result


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Poll task status (for clients that can't use WebSocket)."""
    # In production this would check a Redis/DB task store
    return {"task_id": task_id, "status": "use_websocket", "message": "Use /ws/search/{task_id} for real-time results"}
