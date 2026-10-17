"""Local PDF text extraction and a deliberately simple keyword retrieval step.

Everything here runs on this machine. No file ever leaves the application
directory, and nothing is sent to an external service.

OCR is intentionally NOT implemented. When a PDF looks like a scan we say so
instead of pretending text was extracted.
"""

from __future__ import annotations

import io
import re
import uuid
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_PAGES = 80
MIN_CHARS_FOR_TEXT_PDF = 120

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")

_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "her", "was", "one", "our", "out", "day", "get", "has", "him", "his",
    "how", "man", "new", "now", "old", "see", "two", "way", "who", "did",
    "its", "let", "she", "too", "use", "that", "with", "have", "this",
    "will", "your", "from", "they", "know", "want", "been", "much", "some",
    "time", "very", "when", "come", "here", "just", "like", "long", "make",
    "many", "more", "only", "over", "such", "take", "than", "them", "well",
    "were", "what", "about", "into", "does", "each", "give", "help", "info",
    "information", "please", "tell", "show", "which", "there", "these",
    "those", "would", "could", "should", "document", "statement", "report",
}


def _tokens(text: str) -> list[str]:
    """Lower-cased content words used for keyword matching."""
    out = []
    for raw in _WORD.findall(text.lower()):
        w = raw.strip(".-")
        if len(w) < 3 or w in _STOPWORDS:
            continue
        out.append(w)
    return out


# --------------------------------------------------------------------------- #
# Upload validation + extraction
# --------------------------------------------------------------------------- #
class DocumentError(ValueError):
    """A user-correctable problem with an uploaded file."""


def validate_upload(filename: str, size: int, max_bytes: int, head: bytes) -> None:
    """Reject wrong file types and oversized files before doing any work."""
    if size <= 0:
        raise DocumentError("The uploaded file is empty.")
    if size > max_bytes:
        raise DocumentError(
            f"File is {size / 1_048_576:.1f} MB, which is over the "
            f"{max_bytes / 1_048_576:.0f} MB limit."
        )
    name = (filename or "").lower()
    if not name.endswith(".pdf"):
        raise DocumentError("Only PDF files are accepted (.pdf).")
    if b"%PDF-" not in head[:1024]:
        raise DocumentError(
            "This file does not start with a PDF header, so it is not a real PDF."
        )


def _count_images(page: Any) -> int:
    """Number of embedded raster images on a page (a scan has many, no text)."""
    try:
        resources = page.get("/Resources")
        resources = resources.get_object() if resources else None
        xobj = resources.get("/XObject") if resources else None
        xobj = xobj.get_object() if xobj else None
        if not xobj:
            return 0
        n = 0
        for key in xobj:
            obj = xobj[key].get_object()
            if obj.get("/Subtype") == "/Image":
                n += 1
        return n
    except Exception:  # noqa: BLE001 - image counting is best-effort
        return 0


def extract_pdf(data: bytes, filename: str, max_bytes: int) -> dict[str, Any]:
    """Extract readable text from an uploaded PDF.

    Returns a dict with the text plus enough metadata for the UI to explain
    exactly what happened, including an OCR warning when appropriate.
    """
    validate_upload(filename, len(data), max_bytes, data[:1024])

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                if reader.decrypt("") == 0:
                    raise DocumentError(
                        "This PDF is password protected. Remove the password and "
                        "upload it again."
                    )
            except DocumentError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise DocumentError(
                    "This PDF is password protected and could not be opened."
                ) from exc
        pages = list(reader.pages)
    except DocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, IndexError) as exc:
        raise DocumentError(
            "The PDF could not be read. It may be corrupted or use an unsupported "
            f"feature. ({type(exc).__name__})"
        ) from exc

    if not pages:
        raise DocumentError("This PDF has no pages.")

    truncated = len(pages) > MAX_PAGES
    pages = pages[:MAX_PAGES]

    page_rows: list[dict[str, Any]] = []
    chunks_text: list[str] = []
    total_images = 0

    for index, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - one bad page must not kill the upload
            text = ""
        images = _count_images(page)
        total_images += images
        cleaned = text.strip()
        chunks_text.append(f"--- page {index} ---\n{cleaned}")
        page_rows.append(
            {
                "page": index,
                "chars": len(cleaned),
                "images": images,
                "looks_scanned": images > 0 and len(cleaned) < 80,
            }
        )

    full_text = "\n\n".join(chunks_text).strip()
    total_chars = sum(row["chars"] for row in page_rows)
    looks_scanned = total_chars < MIN_CHARS_FOR_TEXT_PDF and total_images > 0
    almost_empty = total_chars < MIN_CHARS_FOR_TEXT_PDF

    warnings: list[str] = []
    if looks_scanned:
        warnings.append(
            "This PDF looks like a scan: it contains images but almost no "
            "extractable text. OCR is NOT implemented in this app, so no text "
            "could be read. Please upload a text-based (digital) PDF, or run the "
            "file through an OCR tool first and upload the result."
        )
    elif almost_empty:
        warnings.append(
            "Very little text could be extracted from this PDF. It may be an "
            "image-only document that needs OCR (not implemented here)."
        )
    if truncated:
        warnings.append(
            f"The PDF has more than {MAX_PAGES} pages; only the first "
            f"{MAX_PAGES} were read."
        )
    if reader.is_encrypted:
        warnings.append("The PDF was encrypted with an empty password and was opened anyway.")

    empty_pages = [r["page"] for r in page_rows if r["chars"] == 0]

    return {
        "text": full_text,
        "pages": len(page_rows),
        "page_details": page_rows,
        "chars": total_chars,
        "images": total_images,
        "empty_pages": empty_pages,
        "warnings": warnings,
        "needs_ocr": looks_scanned or almost_empty,
        "readable": not (looks_scanned or almost_empty),
    }


# --------------------------------------------------------------------------- #
# Chunking + keyword retrieval (kept intentionally simple)
# --------------------------------------------------------------------------- #
def chunk_text(text: str, size: int = 1100, overlap: int = 150) -> list[str]:
    """Split extracted text into overlapping character windows."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        # Prefer breaking on a line boundary so chunks stay readable.
        if end < len(text):
            nl = text.rfind("\n", start + size // 2, end)
            if nl != -1:
                end = nl + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


def retrieve(chunks: list[str], question: str, k: int = 3) -> dict[str, Any]:
    """Pick the chunks most relevant to the question.

    This is keyword-overlap retrieval, not an embedding model. It is cheap,
    fully local and easy to explain in a classroom, which is why it is used
    here instead of a dense RAG stack.
    """
    if not chunks:
        return {"selected": [], "strategy": "none", "note": "No text to search."}

    # Whole document fits comfortably: no need to drop anything.
    if len(chunks) == 1:
        return {
            "selected": [{"index": 0, "score": 1.0, "text": chunks[0]}],
            "strategy": "full_document",
            "note": "The document is short enough to be sent in full.",
        }

    q_words = list(dict.fromkeys(_tokens(question)))
    scored: list[tuple[int, float]] = []
    for i, chunk in enumerate(chunks):
        if not q_words:
            scored.append((i, 0.0))
            continue
        c_words = set(_tokens(chunk))
        matched = sum(1 for w in q_words if w in c_words)
        # Coverage of the question, damped by chunk length so huge chunks do
        # not win just by containing more words.
        score = matched / len(q_words) if q_words else 0.0
        score = score * (1.0 - 0.15 * min(4, len(c_words) / 400.0))
        scored.append((i, round(score, 4)))

    ranked = sorted(scored, key=lambda row: (-row[1], row[0]))
    top = ranked[:k]

    if all(s == 0 for _, s in top):
        top = [(i, 0.0) for i in range(min(k, len(chunks)))]
        note = (
            "No keyword overlap between the question and the document was found, "
            "so the first chunks were sent as context."
        )
        strategy = "fallback_first_chunks"
    else:
        note = f"Top {len(top)} chunks chosen by question keyword overlap."
        strategy = "keyword_overlap"

    selected = [
        {"index": i, "score": s, "text": chunks[i]}
        for i, s in top
    ]
    return {"selected": selected, "strategy": strategy, "note": note, "scores": scored}


def new_document_id() -> str:
    return uuid.uuid4().hex[:12]
