"""FastAPI routes for SignalForge Vertex AI Gemini Analyst.

Provides:
- GET /api/v1/ai/status: Connectivity and model status in global location.
- GET /api/v1/ai/stocks/{symbol}/context: Compact PostgreSQL snapshot for auditability.
- POST /api/v1/ai/chat: Non-streaming institutional equity research interaction.
- POST /api/v1/ai/chat/stream: Real-time Server-Sent Events (SSE) streaming chat.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from packages.ai.alpha_picks import generate_daily_ai_alpha_picks, get_latest_alpha_picks
from packages.ai.vertex_service import (
    build_compact_stock_snapshot,
    sanitize_text,
    vertex_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: user, assistant, model, or system")
    content: str = Field(..., description="Message text")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User query or analysis request")
    symbol: str | None = Field(default=None, description="Optional stock ticker (e.g. WIPRO, TCS)")
    history: list[ChatMessage] | None = Field(default=None, description="Prior conversation messages")
    model: str | None = Field(default=None, description="Override model name if needed")
    temperature: float | None = Field(default=None, description="Sampling temperature (default 0.2)")


class ChatResponse(BaseModel):
    symbol: str | None = None
    response: str
    model: str
    context_available: bool = False
    context_preview: str | None = None
    raw_context: dict[str, Any] | None = None


@router.get("/status")
async def get_ai_status() -> dict[str, Any]:
    """Checks connectivity to Vertex AI Gemini in the global location."""
    return await vertex_service.get_status()


@router.get("/stocks/{symbol}/context")
async def get_stock_ai_context(symbol: str) -> dict[str, Any]:
    """Retrieves the compact ground-truth PostgreSQL snapshot injected into the model."""
    snapshot = await build_compact_stock_snapshot(symbol)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Stock '{symbol.upper()}' not found or inactive")
    return {
        "symbol": snapshot["symbol"],
        "company_name": snapshot["company_name"],
        "formatted_context": snapshot["formatted_text"],
        "ground_truth": snapshot["raw"],
    }


@router.post("/chat", response_model=ChatResponse)
async def chat_with_ai(request: ChatRequest) -> ChatResponse:
    """Interacts with Vertex AI Gemini using live PostgreSQL ground truth."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    history_dicts = None
    if request.history:
        history_dicts = [{"role": m.role, "content": m.content} for m in request.history]

    try:
        res = await vertex_service.chat(
            message=request.message,
            symbol=request.symbol,
            history=history_dicts,
        )
        return ChatResponse(
            symbol=res["symbol"],
            response=res["response"],
            model=res["model"],
            context_available=res["context_available"],
            context_preview=res.get("context_preview"),
            raw_context=res.get("raw_context"),
        )
    except Exception as exc:
        logger.error(f"Error during AI chat: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_text(str(exc)))


@router.post("/chat/stream")
async def stream_ai_chat(request: ChatRequest) -> StreamingResponse:
    """Streams word-by-word token delivery via Server-Sent Events (SSE)."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    history_dicts = None
    if request.history:
        history_dicts = [{"role": m.role, "content": m.content} for m in request.history]

    generator = vertex_service.chat_stream(
        message=request.message,
        symbol=request.symbol,
        history=history_dicts,
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/alpha-picks")
async def get_ai_alpha_picks(force_refresh: bool = Query(default=False)) -> dict[str, Any]:
    """Retrieves the latest daily multi-factor AI alpha picks and institutional explainability."""
    try:
        return await get_latest_alpha_picks(force_refresh=force_refresh)
    except Exception as exc:
        logger.error(f"Error fetching AI alpha picks: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_text(str(exc)))


@router.post("/alpha-picks/generate")
async def trigger_generate_ai_alpha_picks() -> dict[str, Any]:
    """Triggers on-demand generation of daily AI alpha picks via Vertex AI Gemini."""
    try:
        return await generate_daily_ai_alpha_picks()
    except Exception as exc:
        logger.error(f"Error generating AI alpha picks: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=sanitize_text(str(exc)))
