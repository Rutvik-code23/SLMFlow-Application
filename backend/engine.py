"""SLMFlow integration for the Medical AI demo.

This module never re-implements SLMFlow. It only:

  * builds a :class:`slmflow.ModelRegistry` from the models that are actually
    present in the local Ollama daemon,
  * builds a :class:`slmflow.Pipeline` from a plain config dict,
  * calls ``pipeline.plan()`` and ``pipeline.run()``,
  * captures the library's own structured log events (``route``, ``load``,
    ``evict``, ``step``, ...) so the web UI can show exactly what the
    orchestrator decided and why.

Every number shown in the UI comes from SLMFlow's own ``Result`` / ``RunTrace``
or from Ollama. Nothing is estimated or invented.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import slmflow
from slmflow import MemoryBudget, ModelRegistry, Pipeline, PipelineOptions, probe
from slmflow.types import MemoryFootprint, ModelCard

from .documents import chunk_text, retrieve

__all__ = ["Engine", "EngineConfig", "SLMFLOW_IMPORT_ERROR"]

# --------------------------------------------------------------------------- #
# SLMFlow import status (Feature C asks for this explicitly)
# --------------------------------------------------------------------------- #
try:
    import slmflow as _slmflow_module

    SLMFLOW_IMPORT_ERROR: str | None = None
    SLMFLOW_VERSION: str = getattr(_slmflow_module, "__version__", "unknown")
except Exception as exc:  # noqa: BLE001 - reported to the UI, never hidden
    _slmflow_module = None  # type: ignore[assignment]
    SLMFLOW_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    SLMFLOW_VERSION = "not installed"

_DEFAULT_OLLAMA = "http://localhost:11434"
_STRATEGIES = ("single", "slm_mux", "agent_forest", "cascade", "adaptive")
_SAMPLING_STRATEGIES = {"slm_mux", "agent_forest", "adaptive", "cascade"}


def _gb(value: float) -> int:
    return int(value * 1_000_000_000)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class EngineConfig:
    """Everything the app reads from the environment."""

    def __init__(self) -> None:
        self.ollama_url = (
            os.environ.get("OLLAMA_HOST") or _DEFAULT_OLLAMA
        ).rstrip("/")
        self.mock = os.environ.get("SLMFLOW_MOCK", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.strategy = os.environ.get("SLMFLOW_STRATEGY", "single").strip() or "single"
        if self.strategy not in _STRATEGIES:
            self.strategy = "single"
        self.router = os.environ.get("SLMFLOW_ROUTER", "heuristic").strip() or "heuristic"
        self.scheduler = os.environ.get("SLMFLOW_SCHEDULER", "greedy").strip() or "greedy"
        self.max_output_tokens = _env_int("SLMFLOW_MAX_OUTPUT_TOKENS", 220)
        self.threshold = _env_float("SLMFLOW_CONFIDENCE_THRESHOLD", 0.5)
        self.k = _env_int("SLMFLOW_K", 3)
        self.temperature = _env_float("SLMFLOW_TEMPERATURE", 0.7)
        self.max_models = _env_int("SLMFLOW_MAX_MODELS", 3)
        self.max_model_bytes = _env_int(
            "SLMFLOW_MAX_MODEL_BYTES", 2_500_000_000
        )
        self.vram_budget_gb = os.environ.get("SLMFLOW_VRAM_BUDGET_GB", "").strip()
        self.ram_budget_gb = os.environ.get("SLMFLOW_RAM_BUDGET_GB", "").strip()
        self.max_upload_mb = _env_int("MAX_UPLOAD_MB", 15)
        self.chunk_size = _env_int("CHUNK_SIZE", 1100)
        self.chunk_overlap = _env_int("CHUNK_OVERLAP", 150)
        self.top_k = _env_int("RETRIEVAL_TOP_K", 3)
        self.trace_path = os.environ.get(
            "SLMFLOW_TRACE_PATH", "backend/data/slmflow_runs.jsonl"
        )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1_048_576

    def uses_sampling(self) -> bool:
        return self.strategy in _SAMPLING_STRATEGIES


# --------------------------------------------------------------------------- #
# Structured log capture: SLMFlow logs every routing / residency decision
# --------------------------------------------------------------------------- #
class _EventCapture(logging.Handler):
    """Collects SLMFlow's structured log records for one request."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self._guard = threading.Lock()
        self._sink: list[dict[str, Any]] | None = None

    def start(self) -> list[dict[str, Any]]:
        sink: list[dict[str, Any]] = []
        with self._guard:
            self._sink = sink
        return sink

    def stop(self) -> None:
        with self._guard:
            self._sink = None

    def emit(self, record: logging.LogRecord) -> None:
        with self._guard:
            sink = self._sink
        if sink is None:
            return
        extra = getattr(record, "slmflow", None)
        sink.append(
            {
                "ts": round(record.created, 4),
                "level": record.levelname,
                "logger": record.name,
                "event": getattr(record, "event", record.getMessage()),
                "data": dict(extra) if isinstance(extra, dict) else {},
            }
        )


# Human-readable rendering of the library's own events.
def _fmt_bytes(n: Any) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "n/a"
    if value <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} TB"


def describe_event(event: str, data: dict[str, Any]) -> tuple[str, str, str]:
    """Turn one SLMFlow log event into (category, title, detail)."""
    if event == "route":
        scores = data.get("scores") or {}
        table = ", ".join(f"{m}: {s}" for m, s in scores.items()) or "n/a"
        warm = "already resident (warm, no load cost)" if data.get("warm") else "not resident (cold)"
        return (
            "route",
            f"Router chose '{data.get('chosen', '?')}' for step '{data.get('step', '?')}'",
            f"HeuristicRouter scored every candidate and picked the highest. "
            f"The chosen model was {warm}. Scores: {table}",
        )
    if event == "load":
        evicted = data.get("evicted") or []
        kind = "Cold load" if data.get("cold") else "Warm load"
        return (
            "residency",
            f"ResourceManager loaded '{data.get('model', '?')}'",
            f"{kind} costing {data.get('load_s', 0)}s. "
            f"Measured footprint: VRAM {_fmt_bytes(data.get('vram_bytes'))}, "
            f"RAM {_fmt_bytes(data.get('ram_bytes'))}. "
            f"Evicted to make room: {', '.join(evicted) if evicted else 'nothing'}",
        )
    if event == "evict":
        return (
            "residency",
            f"ResourceManager evicted '{data.get('model', '?')}'",
            "Freed memory so the next model stays inside the declared budget.",
        )
    if event == "step":
        conf = data.get("confidence")
        return (
            "step",
            f"Step '{data.get('step', '?')}' finished on '{data.get('model', '?')}'",
            f"Strategy '{data.get('strategy')}', {data.get('n_generations', 0)} generation(s), "
            f"confidence {conf}, {data.get('swaps', 0)} model swap(s) costing "
            f"{data.get('swap_seconds', 0)}s, step wall time {data.get('wall_s', 0)}s, "
            f"abstained: {data.get('abstained', False)}",
        )
    if event == "mux_select":
        return (
            "strategy",
            f"SLM-MUX picked '{data.get('winner', '?')}'",
            f"Highest self-consistency ({data.get('consistency')}) with contradiction "
            f"rate {data.get('contradiction_rate')}. Per model: {data.get('per_model')}",
        )
    if event == "cascade":
        return (
            "strategy",
            f"Cascade settled on '{data.get('rung', '?')}'",
            f"Rung {data.get('rung_index')} with confidence {data.get('confidence')}; "
            f"escalated: {data.get('escalated')}",
        )
    if event == "adaptive_sampling":
        return (
            "strategy",
            "Adaptive self-consistency stopped sampling",
            json.dumps(data, default=str),
        )
    if event in {"measure_failed", "unload_failed"}:
        return (
            "warning",
            f"SLMFlow reported a non-fatal problem ({event})",
            f"{data}",
        )
    return ("slmflow", f"SLMFlow event: {event}", json.dumps(data, default=str))


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
EXTRACT_PROMPT = (
    "You are reading a medical document (lab report, discharge summary or clinical note).\n"
    "From the evidence above, copy only the sentences and numbers that help "
    "answer the question. Copy every number exactly as written - never recalculate.\n"
    "If nothing in the evidence helps, reply with exactly: NONE\n\n"
    "Question: {question}"
)

ANSWER_PROMPT = (
    "Answer the question using ONLY the evidence above and the extracted facts "
    "in the previous step.\n"
    "Rules:\n"
    "- Never invent numbers, dates, lab values, medications or diagnoses.\n"
    "- Do not perform arithmetic that is not already written in the document.\n"
    "- If the document does not contain the answer, reply with exactly: "
    "The document does not provide enough information.\n\n"
    "Question: {question}\n"
    "Answer in at most 4 sentences."
)


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #
class Engine:
    """Owns the SLMFlow pipeline, the model pool and the Ollama probe."""

    def __init__(self) -> None:
        self.cfg = EngineConfig()
        self._capture = _EventCapture()
        logger = logging.getLogger("slmflow")
        logger.setLevel(logging.INFO)
        logger.propagate = True
        if self._capture not in logger.handlers:
            logger.addHandler(self._capture)

        self._lock = threading.Lock()
        self._pipeline: Pipeline | None = None
        self._pipeline_key: tuple | None = None
        self._registry: ModelRegistry | None = None
        self._cards: list[ModelCard] = []
        self._ollama_models: list[dict[str, Any]] = []
        self._device = None
        self._device_error: str | None = None
        self._last_request: dict[str, Any] | None = None
        self._overrides: dict[str, Any] = {}

        if SLMFLOW_IMPORT_ERROR is None:
            try:
                self._device = probe()
            except Exception as exc:  # noqa: BLE001
                self._device_error = f"{type(exc).__name__}: {exc}"

        self._refresh_models()

    # -- model discovery --------------------------------------------------- #
    def _http_json(self, path: str, timeout: float = 5.0) -> Any:
        req = urllib.request.Request(f"{self.cfg.ollama_url}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def ollama_available(self) -> bool:
        if self.cfg.mock:
            return False
        try:
            return bool(self._http_json("/api/tags", timeout=3.0))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return False

    def _refresh_models(self) -> None:
        """Rebuild the registry from whatever is actually available right now."""
        if SLMFLOW_IMPORT_ERROR is not None:
            return

        if self.cfg.mock:
            from slmflow.models.backends.mock import MockBackend, make_pool

            cards = make_pool(
                [("mock-small", 0.5, 400_000_000), ("mock-large", 3.0, 2_200_000_000)]
            )
            registry = ModelRegistry(cards)
            registry.register_backend(
                "mock",
                MockBackend(
                    default_answer=(
                        "[MOCK OUTPUT - no AI model ran] This is SLMFlow's built-in "
                        "mock backend, used only so the app can be demonstrated "
                        "without Ollama. Configure Ollama for real inference."
                    )
                ),
            )
            self._cards = list(cards)
            self._registry = registry
            self._ollama_models = [
                {"name": c.model_id, "size": c.footprint.ram_bytes, "digest": "mock"}
                for c in cards
            ]
            self._drop_pipeline()
            return

        if not self.ollama_available():
            self._cards = []
            self._registry = None
            self._ollama_models = []
            self._drop_pipeline()
            return

        try:
            payload = self._http_json("/api/tags", timeout=6.0)
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            self._cards = []
            self._registry = None
            self._ollama_models = []
            self._drop_pipeline()
            return

        rows: list[dict[str, Any]] = []
        by_digest: dict[str, dict[str, Any]] = {}
        for entry in payload.get("models", []) or []:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            digest = str(entry.get("digest") or name)
            details = entry.get("details") or {}
            row = by_digest.get(digest)
            if row is None:
                row = {
                    "name": name,
                    "aliases": [],
                    "size": int(entry.get("size") or 0),
                    "digest": digest,
                    "family": details.get("family", ""),
                    "quantisation": details.get("quantisation_level", "")
                    or details.get("quantization_level", ""),
                }
                by_digest[digest] = row
                rows.append(row)
            row["aliases"].append(name)
            row["size"] = max(row["size"], int(entry.get("size") or 0))

        # Ollama lists the same weights under several tags, but /api/ps reports
        # each loaded model under its shortest tag. Using that shortest tag as
        # the model id is what makes SLMFlow's own footprint measurement and
        # is_loaded() check line up with what Ollama actually reports.
        for row in rows:
            row["aliases"].sort(key=len)
            row["name"] = row["aliases"][0]

        rows.sort(key=lambda r: r["size"])
        self._ollama_models = rows

        has_gpu = bool(
            self._device is not None and getattr(self._device.card, "total_vram_bytes", 0) > 0
        )
        selected = [r for r in rows if r["size"] <= self.cfg.max_model_bytes]
        if not selected and rows:
            selected = rows[:1]
        selected = selected[: max(1, self.cfg.max_models)]

        cards = [
            ModelCard(
                model_id=r["name"],
                backend="ollama",
                params_b=0.0,  # not measured - SLMFlow requires None/0 for unknown
                footprint=MemoryFootprint(
                    vram_bytes=r["size"] if has_gpu else 0,
                    ram_bytes=0 if has_gpu else r["size"],
                    disk_bytes=r["size"],
                ),
                context_tokens=8192,
                notes=(
                    "Auto-registered from the local Ollama daemon. "
                    f"On-disk size {_fmt_bytes(r['size'])} as reported by "
                    "/api/tags, declared on the "
                    f"{'VRAM' if has_gpu else 'RAM'} tier. Not profiled, so no "
                    "accuracy or throughput numbers are claimed."
                    + (
                        f" Also known as: {', '.join(r['aliases'][1:])}."
                        if len(r["aliases"]) > 1
                        else ""
                    )
                ),
            )
            for r in selected
        ]

        registry = ModelRegistry(cards)
        from slmflow.models.backends.ollama import OllamaBackend

        registry.register_backend("ollama", OllamaBackend(self.cfg.ollama_url))
        self._cards = cards
        self._registry = registry
        self._drop_pipeline()

    # -- budget ------------------------------------------------------------ #
    def budget(self) -> MemoryBudget:
        if self._device is not None:
            base = MemoryBudget.from_device(self._device.card, headroom=0.75)
        else:
            base = MemoryBudget(vram_bytes=_gb(4), ram_bytes=_gb(6))
        vram = self.cfg.vram_budget_gb
        ram = self.cfg.ram_budget_gb
        return MemoryBudget(
            vram_bytes=_gb(float(vram)) if vram else base.vram_bytes,
            ram_bytes=_gb(float(ram)) if ram else base.ram_bytes,
            disk_bytes=base.disk_bytes,
        )

    # -- pipeline ----------------------------------------------------------- #
    def _drop_pipeline(self) -> None:
        if self._pipeline is not None:
            try:
                self._pipeline.close()
            except Exception:  # noqa: BLE001 - closing must never break anything
                pass
        self._pipeline = None
        self._pipeline_key = None

    def _strategy_settings(self) -> tuple[str, int, float]:
        strategy = self._overrides.get("strategy", self.cfg.strategy)
        if strategy not in _STRATEGIES:
            strategy = "single"
        if strategy in _SAMPLING_STRATEGIES:
            return strategy, max(2, self.cfg.k), max(0.1, self.cfg.temperature)
        return strategy, 1, 0.0

    def _default_answer_model(self) -> str:
        """Largest registered model, used for the answer step by default.

        The extract step stays router-decided, so routing is still exercised on
        every request. Pinning the answer step to the biggest local model is a
        configuration choice, not a measurement claim - and the UI lets you
        switch it back to "router decides" to compare.
        """
        if not self._cards:
            return ""
        return max(self._cards, key=lambda c: c.footprint.resident_bytes).model_id

    def _answer_model(self) -> str:
        """Model pinned to the answer step, or '' to let the router decide."""
        if "answer_model" in self._overrides:
            return str(self._overrides["answer_model"])
        env = os.environ.get("SLMFLOW_ANSWER_MODEL", "").strip()
        if env.lower() in {"router", "auto", "none"}:
            return ""
        if env:
            return env
        return self._default_answer_model()

    def _config_dict(self, question: str) -> dict[str, Any]:
        strategy, k, temperature = self._strategy_settings()
        answer_step: dict[str, Any] = {
            "name": "answer",
            "task_type": "qa",
            "depends_on": ["extract_facts"],
            "prompt": ANSWER_PROMPT,
            "threshold": self.cfg.threshold,
            "max_output_tokens": self.cfg.max_output_tokens,
        }
        if strategy != "single":
            answer_step.update(
                {"strategy": strategy, "k": k, "temperature": temperature}
            )
        pinned = self._answer_model()
        if pinned:
            answer_step["model"] = pinned
        return {
            "name": "medical_document_qa",
            "router": self.cfg.router,
            "scheduler": self.cfg.scheduler,
            "steps": [
                {
                    "name": "extract_facts",
                    "task_type": "extract",
                    "prompt": EXTRACT_PROMPT,
                    "threshold": self.cfg.threshold,
                    "max_output_tokens": min(200, self.cfg.max_output_tokens),
                },
                answer_step,
            ],
        }

    def _pipeline_for(self, question: str) -> Pipeline:
        assert self._registry is not None
        strategy, _, _ = self._strategy_settings()
        key = (
            strategy,
            self._answer_model(),
            self.cfg.router,
            self.cfg.scheduler,
        )
        if self._pipeline is not None and self._pipeline_key == key:
            return self._pipeline

        self._drop_pipeline()
        options = PipelineOptions(trace_path=self.cfg.trace_path)
        pipeline = Pipeline(
            slmflow.parse_config(self._config_dict(question)),
            self._registry,
            budget=self.budget(),
            options=options,
            device=self._device,
        )
        self._pipeline = pipeline
        self._pipeline_key = key
        return pipeline

    # -- status ------------------------------------------------------------- #
    def status(self) -> dict[str, Any]:
        strategy, k, temperature = self._strategy_settings()
        budget = self.budget()
        ollama_up = self.ollama_available()

        describe: dict[str, Any] | None = None
        describe_error: str | None = None
        if self._registry is not None and self._cards:
            try:
                pipeline = self._pipeline_for("status probe")
                describe = json.loads(json.dumps(pipeline.describe(), default=str))
            except Exception as exc:  # noqa: BLE001
                describe_error = f"{type(exc).__name__}: {exc}"

        residency: dict[str, Any] | None = None
        if self._pipeline is not None:
            manager = self._pipeline.manager
            footprint = manager.current_footprint()
            residency = {
                "resident_models": list(manager.resident_models),
                "vram_bytes": footprint.vram_bytes,
                "ram_bytes": footprint.ram_bytes,
                "ledger": json.loads(json.dumps(manager.ledger.snapshot(), default=str)),
                "concurrency_limit": self._pipeline.concurrency_limit(),
            }

        return {
            "slmflow": {
                "version": SLMFLOW_VERSION,
                "import_ok": SLMFLOW_IMPORT_ERROR is None,
                "import_error": SLMFLOW_IMPORT_ERROR,
                "mock": self.cfg.mock,
            },
            "backend": {
                "name": "mock" if self.cfg.mock else "ollama",
                "url": self.cfg.ollama_url,
                "available": True if self.cfg.mock else ollama_up,
                "registered_models": [
                    {
                        "model_id": c.model_id,
                        "params_b": c.params_b,
                        "profiled": c.is_profiled,
                        "declared_vram_bytes": c.footprint.vram_bytes,
                        "context_tokens": c.context_tokens,
                        "notes": c.notes,
                    }
                    for c in self._cards
                ],
                "ollama_models": self._ollama_models,
            },
            "config": {
                "strategy": strategy,
                "k": k,
                "temperature": temperature,
                "router": self.cfg.router,
                "scheduler": self.cfg.scheduler,
                "threshold": self.cfg.threshold,
                "max_output_tokens": self.cfg.max_output_tokens,
                "answer_model": pinned_or_empty(self),
                "budget": {
                    "vram_bytes": budget.vram_bytes,
                    "ram_bytes": budget.ram_bytes,
                },
                "chunk_size": self.cfg.chunk_size,
                "top_k": self.cfg.top_k,
            },
            "device": json.loads(json.dumps(self._device.card, default=str)) if self._device else None,
            "device_error": self._device_error,
            "describe": describe,
            "describe_error": describe_error,
            "residency": residency,
            "last_request": self._last_request,
            "setup": self.setup_instructions(ollama_up),
        }

    def setup_instructions(self, ollama_up: bool | None = None) -> str:
        if SLMFLOW_IMPORT_ERROR is not None:
            return (
                "SLMFlow could not be imported. Reinstall it with: "
                "pip install --index-url https://test.pypi.org/simple/ --no-deps slmflow==0.1.1"
            )
        if self.cfg.mock:
            return (
                "Running in MOCK mode (SLMFLOW_MOCK=1). SLMFlow's own mock backend is "
                "answering - these are scripted strings, NOT model inference. "
                "Unset SLMFLOW_MOCK and install Ollama for real answers."
            )
        up = self.ollama_available() if ollama_up is None else ollama_up
        if not up:
            return (
                f"Ollama is not reachable at {self.cfg.ollama_url}.\n"
                "1. Install Ollama from https://ollama.com/download\n"
                "2. Start it:  ollama serve\n"
                "3. Pull a small model:  ollama pull qwen2.5:0.5b\n"
                "4. Restart this app. Real AI answers stay disabled until then."
            )
        if not self._cards:
            return (
                "Ollama is running but no small enough model was registered. "
                "Pull one with:  ollama pull qwen2.5:0.5b   then restart the app."
            )
        return (
            f"Ready. Backend 'ollama' at {self.cfg.ollama_url} with "
            f"{len(self._cards)} registered model(s)."
        )

    # -- asking questions ---------------------------------------------------- #
    def ask(self, text: str, question: str) -> dict[str, Any]:
        """Chunk, retrieve, plan, run the pipeline, and record every step."""
        with self._lock:
            started = time.perf_counter()
            timeline: list[dict[str, Any]] = []

            def add(category: str, title: str, detail: str, source: str,
                    data: Any = None) -> None:
                timeline.append(
                    {
                        "n": len(timeline) + 1,
                        "category": category,
                        "title": title,
                        "detail": detail,
                        "source": source,
                        "data": data,
                    }
                )

            if SLMFLOW_IMPORT_ERROR is not None:
                raise RuntimeError(f"SLMFlow is not importable: {SLMFLOW_IMPORT_ERROR}")
            if self._registry is None or not self._cards:
                raise RuntimeError(self.setup_instructions())

            chunks = chunk_text(text, self.cfg.chunk_size, self.cfg.chunk_overlap)
            retrieval = retrieve(chunks, question, self.cfg.top_k)
            selected = retrieval["selected"]
            add(
                "ingest",
                f"Document split into {len(chunks)} chunk(s)",
                f"Chunk size {self.cfg.chunk_size} characters with "
                f"{self.cfg.chunk_overlap} characters of overlap.",
                "app",
                {"chunks": len(chunks)},
            )
            add(
                "retrieve",
                f"Retrieved {len(selected)} chunk(s) as evidence",
                f"{retrieval['note']} Method: {retrieval['strategy']} "
                "(keyword overlap, not an embedding model).",
                "app",
                {"selected": [{"index": s["index"], "score": s["score"]} for s in selected]},
            )

            strategy, k, temperature = self._strategy_settings()
            answer_model = self._answer_model()
            add(
                "config",
                "Pipeline configuration resolved",
                f"strategy='{strategy}', router='{self.cfg.router}', "
                f"scheduler='{self.cfg.scheduler}', abstention threshold="
                f"{self.cfg.threshold}, budget {self.budget().describe()}",
                "app",
            )
            if answer_model:
                add(
                    "config",
                    f"Step 'answer' is pinned to '{answer_model}'",
                    "The router is skipped for this step because the step declares a "
                    "fixed model. Step 'extract_facts' is still routed over every "
                    "registered model. Clear the pin on the status card to let the "
                    "router decide for both steps.",
                    "app",
                )
            else:
                add(
                    "config",
                    "No model is pinned: the router chooses every step",
                    "Both steps list every registered model as a candidate, so the "
                    "router scores all of them twice.",
                    "app",
                )

            pipeline = self._pipeline_for(question)

            plan_info: dict[str, Any] | None = None
            try:
                schedule = pipeline.plan({"question": question})
                plan_info = {
                    "planner": schedule.planner,
                    "predicted_seconds": schedule.predicted_seconds,
                    "predicted_quality": schedule.predicted_quality,
                    "predicted_loads": schedule.predicted_loads,
                    "peak_vram_bytes": schedule.peak_footprint.vram_bytes,
                    "peak_ram_bytes": schedule.peak_footprint.ram_bytes,
                    "entries": [
                        {
                            "step": e.step,
                            "model_id": e.model_id,
                            "load_before": e.load_before,
                            "evict_before": list(e.evict_before),
                        }
                        for e in schedule.entries
                    ],
                }
                entries = ", ".join(
                    f"{e['step']} -> {e['model_id']}"
                    f"{' (load)' if e['load_before'] else ' (reuse)'}"
                    for e in plan_info["entries"]
                )
                add(
                    "plan",
                    f"Scheduler '{schedule.planner}' produced an execution plan",
                    f"{entries}. Predicted model loads: {schedule.predicted_loads}. "
                    "Predicted seconds/quality are 'null' when the model cards are "
                    "not profiled - SLMFlow refuses to invent them.",
                    "slmflow",
                    plan_info,
                )
            except Exception as exc:  # noqa: BLE001 - planning must not hide the error
                add(
                    "warning",
                    "Could not build an execution plan",
                    f"{type(exc).__name__}: {exc}",
                    "slmflow",
                )

            events = self._capture.start()
            result: Any = None
            run_error: str | None = None
            run_error_type: str | None = None
            install_hint: str | None = None
            try:
                result = pipeline.run(
                    {"question": question}, retrieved=[s["text"] for s in selected]
                )
            except Exception as exc:  # noqa: BLE001 - surfaced honestly to the UI
                run_error = str(exc) or repr(exc)
                run_error_type = type(exc).__name__
                install_hint = getattr(exc, "install_hint", None)
            finally:
                self._capture.stop()

            for event in events:
                category, title, detail = describe_event(event["event"], event["data"])
                add(category, title, detail, "slmflow", event["data"])

            steps: list[dict[str, Any]] = []
            answer = None
            confidence = None
            abstained = False
            abstention_reason = None
            trace_info: dict[str, Any] | None = None
            ok = result is not None and not result.abstained and run_error is None

            if result is not None:
                answer = result.answer
                confidence = result.confidence
                abstained = bool(result.abstained)
                abstention_reason = (
                    str(result.abstention_reason) if result.abstention_reason else None
                )
                for step in result.trace.steps:
                    steps.append(
                        {
                            "step": step.step,
                            "model_id": step.model_id,
                            "strategy": step.strategy,
                            "confidence": step.confidence,
                            "confidence_signals": dict(step.confidence_signals),
                            "swaps": step.swaps,
                            "swap_seconds": round(step.swap_seconds, 4),
                            "peak_vram_bytes": step.peak_vram_bytes,
                            "peak_ram_bytes": step.peak_ram_bytes,
                            "abstained": step.abstained,
                            "abstention_reason": (
                                str(step.abstention_reason)
                                if step.abstention_reason
                                else None
                            ),
                            "error": step.error,
                            "wall_s": round(step.wall_s, 4),
                            "generations": [
                                {
                                    "model_id": g.model_id,
                                    "prompt_tokens": g.prompt_tokens,
                                    "output_tokens": g.output_tokens,
                                    "latency_s": round(g.latency_s, 4),
                                    "load_s": round(g.load_s, 4),
                                    "was_cold": g.was_cold,
                                    "finish_reason": g.finish_reason,
                                    "schema_valid": g.schema_valid,
                                }
                                for g in step.generations
                            ],
                        }
                    )
                trace = result.trace
                trace_info = {
                    "run_id": trace.run_id,
                    "pipeline": trace.pipeline,
                    "device": trace.device,
                    "config_digest": trace.config_digest,
                    "wall_s": round(trace.wall_s, 4),
                    "total_swaps": trace.total_swaps,
                    "swap_seconds": round(trace.swap_seconds, 4),
                    "total_generations": trace.total_generations,
                    "output_tokens": trace.output_tokens,
                    "peak_vram_bytes": trace.peak_vram_bytes,
                    "peak_ram_bytes": trace.peak_ram_bytes,
                    "models_used": list(trace.models_used),
                }

            elapsed = time.perf_counter() - started

            if run_error is not None:
                ok = False
                add(
                    "result",
                    "The SLMFlow pipeline raised an error",
                    f"{run_error_type}: {run_error}"
                    + (f"  Hint: {install_hint}" if install_hint else ""),
                    "app",
                )
            elif abstained:
                add(
                    "result",
                    "SLMFlow abstained",
                    f"abstention_reason={abstention_reason}, confidence={confidence}, "
                    f"threshold={self.cfg.threshold}. The library declined to return "
                    "an answer rather than guess.",
                    "app",
                )
            else:
                add(
                    "result",
                    f"Answer produced in {elapsed:.2f}s",
                    f"Confidence {confidence}, {trace_info['total_swaps'] if trace_info else 0} "
                    "model swap(s) across the run.",
                    "app",
                )

            summary = {
                "ok": ok,
                "answer": answer,
                "confidence": confidence,
                "abstained": abstained,
                "abstention_reason": abstention_reason,
                "response_time_s": round(elapsed, 3),
                "error": run_error,
                "error_type": run_error_type,
                "install_hint": install_hint,
                "mock": self.cfg.mock,
                "strategy": strategy,
            }
            self._last_request = summary

            manager = pipeline.manager
            footprint = manager.current_footprint()
            return {
                **summary,
                "retrieval": {
                    "chunks_total": len(chunks),
                    "chunk_size": self.cfg.chunk_size,
                    "top_k": self.cfg.top_k,
                    "strategy": retrieval["strategy"],
                    "note": retrieval["note"],
                    "selected": selected,
                },
                "plan": plan_info,
                "describe": json.loads(json.dumps(pipeline.describe(), default=str)),
                "steps": steps,
                "trace": trace_info,
                "timeline": timeline,
                "raw_events": events,
                "residency": {
                    "resident_models": list(manager.resident_models),
                    "vram_bytes": footprint.vram_bytes,
                    "ram_bytes": footprint.ram_bytes,
                    "ledger": json.loads(
                        json.dumps(manager.ledger.snapshot(), default=str)
                    ),
                },
            }

    # -- runtime configuration ---------------------------------------------- #
    def apply_overrides(self, body: dict[str, Any]) -> dict[str, Any]:
        strategy = body.get("strategy")
        if strategy is not None:
            if strategy not in _STRATEGIES:
                raise ValueError(
                    f"Unknown strategy {strategy!r}. Valid: {', '.join(_STRATEGIES)}"
                )
            self._overrides["strategy"] = strategy
        model = body.get("answer_model")
        if model is not None:
            model = str(model).strip()
            if model and model not in {c.model_id for c in self._cards}:
                raise ValueError(f"Model {model!r} is not registered.")
            self._overrides["answer_model"] = model
        self._drop_pipeline()
        return self.status()

    def reset(self) -> dict[str, Any]:
        self._overrides.clear()
        self._drop_pipeline()
        self._refresh_models()
        return self.status()


def pinned_or_empty(engine: Engine) -> str:
    return engine._answer_model()
