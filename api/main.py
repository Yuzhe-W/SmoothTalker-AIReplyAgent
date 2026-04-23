import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import get_session, get_session_factory, init_db
from .curated_sync import CuratedDatasetSyncService
from .db_models import delete_thread_data, get_reply_session, list_recent_threads, record_reply_session
from .guardrails import apply_role_guardrails, parse_numbered_output, redact_privacy
from .models import (
    DeleteThreadRequest,
    GenerateRequest,
    GenerateResponse,
    SelectRequest,
    SimpleResponse,
    ThreadItem,
    ThreadsRequest,
    ThreadsResponse,
)
from .rag_service import ReplyRAGService
from .settings import MODEL, PROVIDER

app = FastAPI(title="SmoothTalker MVP", version="0.2.0")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("reply_copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_service: ReplyRAGService | None = None
_curated_sync_service: CuratedDatasetSyncService | None = None


def _get_service() -> ReplyRAGService:
    if _service is None:
        raise HTTPException(status_code=503, detail="RAG service unavailable")
    return _service


def _parse_options(role: str, raw: str) -> list[str]:
    try:
        options = parse_numbered_output(raw)
    except Exception:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        options = lines[:3]

    options = [apply_role_guardrails(role, option) for option in options if option.strip()]
    if not options:
        raise HTTPException(status_code=502, detail="Model returned no usable reply options")
    while len(options) < 3:
        options.append(options[-1])
    return options[:3]


@app.on_event("startup")
def _startup() -> None:
    global _service, _curated_sync_service
    try:
        init_db()
        _service = ReplyRAGService(get_session_factory())
        _curated_sync_service = CuratedDatasetSyncService(get_session_factory())
        sync_result = _curated_sync_service.sync()
        logger.info(
            "Curated dataset sync: skipped=%s inserted=%s updated=%s deleted=%s unchanged=%s accepted_backfilled=%s count=%s",
            sync_result.skipped,
            sync_result.inserted,
            sync_result.updated,
            sync_result.deleted,
            sync_result.unchanged,
            sync_result.accepted_backfilled,
            sync_result.example_count,
        )
    except Exception as exc:
        logger.error("Startup failed: %s", exc)
        raise


@app.get("/")
def root():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "provider": PROVIDER, "model": MODEL}


@app.post("/v1/replies:generate", response_model=GenerateResponse)
def generate(req: GenerateRequest, db: Session = Depends(get_session)):
    service = _get_service()

    role = (req.role or "").lower().strip()
    if role not in {"crush", "colleague"}:
        raise HTTPException(status_code=400, detail="role must be 'crush' or 'colleague'")

    incoming = redact_privacy(req.incoming_text).strip()
    if not incoming:
        raise HTTPException(status_code=400, detail="incoming_text cannot be empty after redaction")

    thread_id = (req.thread_id or "").strip()
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    try:
        thread_summary = service.get_thread_summary(
            db,
            external_user_id=req.user_id,
            thread_id=thread_id,
            role=role,
        )
        examples = service.retrieve_examples(
            external_user_id=req.user_id,
            thread_id=thread_id,
            role=role,
            incoming_text=incoming,
            thread_summary=thread_summary,
        )
        result = service.generate(
            role=role,
            incoming_text=incoming,
            thread_summary=thread_summary,
            examples=examples,
        )
    except Exception as exc:
        logger.error("RAG generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"LLM service error: {exc}") from exc

    raw = result.text or ""
    logging.info("raw_model_text: %s", raw[:400].replace("\n", "\\n"))
    options = _parse_options(role, raw)
    meta = service.build_meta(result)

    try:
        reply_session = record_reply_session(
            db,
            external_user_id=req.user_id,
            thread_id=thread_id,
            role=role,
            incoming_text=incoming,
            options=options,
            meta=meta,
        )
    except Exception as exc:
        logger.error("Failed to persist reply session: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to persist reply session") from exc

    return GenerateResponse(options=options, session_id=reply_session.id, meta=meta)


@app.post("/v1/replies:select", response_model=SimpleResponse)
def select_reply(req: SelectRequest, db: Session = Depends(get_session)):
    service = _get_service()
    reply_session = get_reply_session(db, req.session_id)
    if reply_session is None:
        raise HTTPException(status_code=404, detail="session_id not found")

    if reply_session.thread_id != req.thread_id:
        raise HTTPException(status_code=400, detail="thread_id does not match the stored session")

    if req.option_index >= len(reply_session.options):
        raise HTTPException(status_code=400, detail="option_index is out of range")

    if req.user_id:
        session_user_id = reply_session.user.external_id if reply_session.user else "anonymous"
        lookup = req.user_id.strip() or "anonymous"
        if session_user_id != lookup:
            raise HTTPException(status_code=400, detail="user_id does not match the stored session")

    try:
        service.select_reply(
            db,
            reply_session=reply_session,
            external_user_id=req.user_id,
            thread_id=req.thread_id,
            option_index=req.option_index,
        )
    except Exception as exc:
        logger.error("Failed to store selected reply: %s", exc)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to store selected reply") from exc

    return SimpleResponse(ok=True)


@app.post("/v1/threads:list", response_model=ThreadsResponse)
def list_threads(req: ThreadsRequest, db: Session = Depends(get_session)):
    threads = list_recent_threads(
        db,
        external_user_id=req.user_id,
        role=req.role,
        limit=req.limit,
    )
    return ThreadsResponse(
        threads=[
            ThreadItem(
                thread_id=thread.thread_id,
                role=thread.role,
                summary=(thread.summary or "").strip(),
                updated_at=thread.updated_at.isoformat(),
            )
            for thread in threads
        ]
    )


@app.post("/v1/threads:delete", response_model=SimpleResponse)
def delete_thread(req: DeleteThreadRequest, db: Session = Depends(get_session)):
    deleted = delete_thread_data(
        db,
        external_user_id=req.user_id,
        thread_id=req.thread_id,
        role=req.role,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="thread_id not found")
    return SimpleResponse(ok=True)
