"""SLMFlow Medical AI - FastAPI backend.

Run it with:  uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from .documents import DocumentError, extract_pdf, new_document_id  # noqa: E402
from .engine import Engine  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DIST_DIR = ROOT / "frontend" / "dist"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_QUESTION = 2000
MAX_STORED_CHARS = 400_000

app = FastAPI(title="SLMFlow Medical AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = Engine()
DOCUMENTS: dict[str, dict[str, Any]] = {}


# --------------------------------------------------------------------------- #
# Status / configuration
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": time.time()}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return engine.status()


@app.post("/api/status/refresh")
def refresh() -> dict[str, Any]:
    """Re-scan Ollama for models (useful after `ollama pull ...`)."""
    return engine.reset()


class ConfigRequest(BaseModel):
    strategy: str | None = None
    answer_model: str | None = None


@app.post("/api/config")
def update_config(payload: ConfigRequest) -> dict[str, Any]:
    try:
        return engine.apply_overrides(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
@app.post("/api/documents")
def upload_document(file: UploadFile = File(...)) -> dict[str, Any]:
    """Extract text from an uploaded PDF.

    Declared as a plain ``def`` on purpose: FastAPI runs sync endpoints in a
    worker thread, which is also what SLMFlow needs later (``Pipeline.run``
    calls ``asyncio.run`` internally, so it must not be called on the event
    loop thread).
    """
    started = time.perf_counter()
    data = file.file.read()
    try:
        info = extract_pdf(data, file.filename or "", engine.cfg.max_upload_bytes)
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    doc_id = new_document_id()
    safe_name = os.path.basename(file.filename or "document.pdf")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = UPLOAD_DIR / f"{doc_id}.pdf"
    stored_path.write_bytes(data)

    text = info["text"]
    truncated = False
    if len(text) > MAX_STORED_CHARS:
        text = text[:MAX_STORED_CHARS]
        truncated = True
        info["warnings"].append(
            f"Extracted text was longer than {MAX_STORED_CHARS} characters and was "
            "truncated for the preview and for questions."
        )

    record = {
        "id": doc_id,
        "filename": safe_name,
        "bytes": len(data),
        "pages": info["pages"],
        "chars": len(text),
        "text": text,
        "page_details": info["page_details"],
        "images": info["images"],
        "warnings": info["warnings"],
        "needs_ocr": info["needs_ocr"],
        "readable": info["readable"],
        "truncated": truncated,
        "stored_path": str(stored_path),
        "extract_time_s": round(time.perf_counter() - started, 3),
        "uploaded_at": time.time(),
    }
    DOCUMENTS[doc_id] = record
    return public_document(record)


def public_document(record: dict[str, Any], include_text: bool = True) -> dict[str, Any]:
    out = {k: v for k, v in record.items() if k not in {"stored_path", "text"}}
    if include_text:
        out["text"] = record["text"]
    return out


@app.get("/api/documents")
def list_documents() -> dict[str, Any]:
    rows = [
        public_document(r, include_text=False)
        for r in sorted(DOCUMENTS.values(), key=lambda r: -r["uploaded_at"])
    ]
    return {"documents": rows}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str) -> dict[str, Any]:
    record = DOCUMENTS.get(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return public_document(record)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict[str, Any]:
    record = DOCUMENTS.pop(doc_id, None)
    if record is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    try:
        Path(record["stored_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Asking questions
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    document_id: str
    question: str


@app.post("/api/ask")
def ask(payload: AskRequest) -> dict[str, Any]:
    """Answer a question about an uploaded document through SLMFlow.

    Also a plain ``def`` so the SLMFlow pipeline runs on a worker thread
    (see the note on ``upload_document``).
    """
    doc_id = payload.document_id
    question = (payload.question or "").strip()

    record = DOCUMENTS.get(doc_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Upload a document first.")
    if len(question) < 4:
        raise HTTPException(status_code=400, detail="Please type a real question.")
    if len(question) > MAX_QUESTION:
        raise HTTPException(
            status_code=400, detail=f"Question is longer than {MAX_QUESTION} characters."
        )
    if not record["readable"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "No readable text was extracted from this PDF (it is probably a "
                "scan). OCR is not implemented, so questions cannot be answered "
                "from it."
            ),
        )

    try:
        return engine.ask(record["text"], question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - never hide a failure from the user
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "answer": None,
                "error": f"{type(exc).__name__}: {exc}",
                "error_type": type(exc).__name__,
                "response_time_s": 0.0,
                "timeline": [],
                "steps": [],
                "trace": None,
                "plan": None,
            },
        )


# --------------------------------------------------------------------------- #
# Static frontend (production build)
#
# The built index.html is returned as a real HTML response. Returning the raw
# string would make FastAPI JSON-encode it, which browsers render as a quoted
# JSON literal instead of a page.
# --------------------------------------------------------------------------- #
def _index_html() -> HTMLResponse:
    return HTMLResponse((DIST_DIR / "index.html").read_text(encoding="utf-8"))


if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> HTMLResponse:
        return _index_html()

    @app.get("/{path:path}")
    def spa(path: str) -> HTMLResponse:
        candidate = (DIST_DIR / path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(DIST_DIR.resolve())):
            return HTMLResponse(candidate.read_text(encoding="utf-8"))
        return _index_html()
else:
    @app.get("/")
    def index() -> dict[str, str]:
        return {
            "message": (
                "SLMFlow Medical AI backend is running, but the frontend has not "
                "been built yet. Run  .\\start.ps1  (or: cd frontend; npm install; "
                "npm run build) and then reload this page."
            ),
            "api": "/api/status",
            "upload": "POST /api/documents (multipart, field 'file')",
            "ask": "POST /api/ask  ({document_id, question})",
        }
