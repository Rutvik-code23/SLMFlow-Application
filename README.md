# SLMFlow Medical AI

A small college-project demo: upload a medical PDF (lab report, discharge
summary or prescription) and ask questions about it. The question answering is
orchestrated by
**[SLMFlow](https://github.com/Aashi28487/SLMFlow)**, a Python library for
running pipelines of small language models on local hardware.

Everything runs on your own machine. The PDF is read locally and inference
happens in a local **Ollama** model. Nothing is sent to any external service.

The interesting part is not the chat — it is the **execution trace panel**, which
shows what SLMFlow actually did: the schedule it planned, which model the router
picked and why, what it had to load or evict, and the confidence it scored the
answer with.

---

## 1. Required software

| Software | Version | Why |
|---|---|---|
| Python | 3.10, 3.11, 3.12 or 3.13 | runs the backend and SLMFlow |
| Node.js | 18 or newer | builds the React frontend |
| Ollama | any recent build | runs the small local model (optional but needed for real answers) |

Check they are installed:

```powershell
python --version
node --version
ollama --version
```

---

## 2. Create and activate the virtual environment

Open PowerShell **in the project folder** and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run activation scripts, run this once in an
**administrator** PowerShell and then close it:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## 3. Install SLMFlow from TestPyPI

SLMFlow is published on TestPyPI, and `--no-deps` is required because TestPyPI
does not host its transitive requirements. SLMFlow's core has **zero** required
dependencies, so nothing is missed.

```powershell
python -m pip install --upgrade pip
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps slmflow==0.1.1
```

Verify it is really installed:

```powershell
python -c "import slmflow; print(slmflow.__version__)"
```

Expected output: `0.1.1`

---

## 4. Install the other dependencies

```powershell
python -m pip install -r requirements.txt
```

Then install the frontend packages and build the UI:

```powershell
cd frontend
npm install
npm run build
cd ..
```

> **Shortcut:** `.\start.ps1` does steps 2 to 4 and then starts the app.

---

## 5. Configure Ollama and a model

Install Ollama from <https://ollama.com/download>, then pull a small model. The
0.5B and 1.5B Qwen models are quick; the 3B Llama model gives noticeably better
answers.

```powershell
ollama serve
ollama pull qwen2.5:0.5b
ollama pull llama3.2:3b
```

`ollama serve` normally starts automatically in the background on Windows. The
app talks to `http://localhost:11434`; set `OLLAMA_HOST` if yours is elsewhere.

The app **detects your local models by itself** and registers the three smallest
ones (up to 2.5 GB each) with SLMFlow. To change which ones, use
`SLMFLOW_MAX_MODELS` and `SLMFLOW_MAX_MODEL_BYTES` (see `.env.example`).

**No model configured?** The app still starts. The status card shows the exact
commands to run, and questions are refused rather than answered with something
fake.

### Optional: demo the UI without any model

```powershell
$env:SLMFLOW_MOCK = "1"
.\start.ps1 -SkipInstall
```

This uses SLMFlow's own built-in `MockBackend`. Every answer and every run is
badged **MOCK** in the UI. It is scripted text, **not** model inference — useful
only to show the interface.

---

## 6. Start the app

```powershell
.\start.ps1
```

That creates the venv if needed, installs everything, builds the UI and starts
the server.

To run the pieces by hand instead:

```powershell
# terminal 1 - backend (also serves the built UI)
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# terminal 2 - optional Vite dev server, with hot reload
cd frontend
npm run dev
```

---

## 7. Which URL to open

| Mode | URL |
|---|---|
| Normal (`.\start.ps1`) | <http://127.0.0.1:8000> |
| Dev mode (`.\start.ps1 -Dev`) | <http://127.0.0.1:5173> |

---

## 8. How to use it

1. **Upload a PDF.** Drag `sample/sample_medical_report.pdf` (included) onto
   the upload card, or click to pick your own lab report, prescription or
   discharge summary.
2. **Read the extracted text** in the preview panel. If the PDF is a scan, the
   app says so — OCR is not implemented here, so a scanned file cannot be used.
3. **Ask a question.** Click one of the suggestion chips or type your own, e.g.
   *What is the primary diagnosis mentioned in this document?*
4. **Watch the execution trace.** Under the chat you will see, in order:
   the chunks sent as context, the schedule SLMFlow planned, the router's score
   for every candidate model, the model load and its measured cost, each step
   finishing with its confidence, and the final `RunTrace`.

Try switching the **execution strategy** on the status card from `single` to
`cascade`, `slm_mux` or `adaptive` and ask again — the trace changes, and the
sampling strategies produce a real self-consistency confidence instead of a
constant 1.0.

---

## What each feature does

**A — Upload a medical document.** PDFs are validated (type, size, real PDF
header, password protection) and read with `pypdf`. Text is extracted locally
and stored in `backend/data/uploads/`. Scanned/image-only PDFs are detected by
counting embedded images against the amount of extractable text, and the user is
told OCR is needed instead of being shown an empty result.

**B — Ask questions about the document.** The extracted text is split into
overlapping chunks and the chunks with the most keyword overlap with the
question are sent as evidence. This is deliberately simple keyword retrieval,
not a dense RAG stack. The question and evidence go into a real SLMFlow pipeline
with two dependent steps, and the prompt tells the model to say the document
does not have the answer rather than invent one.

**C — Powered by SLMFlow.** The status card shows the installed version, whether
the import succeeded, the selected strategy, the configured backend and models,
whether the last request succeeded, the application-measured response time, the
answer, SLMFlow's own confidence and abstention status, and the full
`RunTrace` (run id, wall time, swaps, tokens, peak memory, config digest).

**D — Simple model setup.** The backend checks that the Ollama daemon is
reachable and that at least one usable model exists before enabling questions.
If not, it prints the exact install and `ollama pull` commands.

---

## How SLMFlow is actually used

Only published SLMFlow APIs are used — nothing is reimplemented.

| What the app does | SLMFlow API |
|---|---|
| Register local models | `ModelRegistry`, `ModelCard`, `MemoryFootprint` |
| Attach the backend | `registry.register_backend("ollama", OllamaBackend(...))` |
| Declare the memory budget | `MemoryBudget.from_device(slmflow.probe().card)` |
| Build the pipeline | `Pipeline(slmflow.parse_config(cfg), registry, budget=..., options=..., device=...)` |
| Show the plan before running | `pipeline.plan({"question": ...})` → `Schedule` |
| Answer a question | `pipeline.run(inputs, retrieved=[...])` → `Result` |
| Show what happened | the library's own log events (`route`, `load`, `evict`, `step`) plus `Result.trace` (`RunTrace`) |
| Write SLMFlow's own trace file | `PipelineOptions(trace_path=...)` → `backend/data/slmflow_runs.jsonl` |

The pipeline has two steps: `extract_facts` (mechanical extraction, routed over
every registered model) and `answer` (`depends_on: ["extract_facts"]`, so SLMFlow
passes the extracted facts forward and the router's choice is pinned to the
largest registered model by default — change it on the status card).

---

## Honest limitations

- **Answers are only as good as the small local model.** A 0.5B model often
  misses details a 3B model finds. That is the trade-off this demo is built to
  make visible.
- **No figure is independently verified.** The app tells the model not to do
  arithmetic that is not in the document, but a small model can still compute
  wrongly. Treat every number as "what the model said about the document".
- **The confidence is SLMFlow's self-consistency signal.** With the `single`
  strategy there is only one sample, so the confidence is a constant `1.0` and
  means very little. Switch to `slm_mux`, `adaptive` or `cascade` for a real
  spread. SLMFlow does not report a calibrated probability.
- **Model cards are not profiled.** No accuracy or throughput was measured on
  this machine, so SLMFlow leaves predicted seconds and quality as `null` and
  applies its unprofiled penalty when routing. The UI says so rather than
  filling the gap with invented numbers.
- **Retrieval is keyword overlap**, not embeddings. It is cheap and explainable,
  and it is not a claim about retrieval quality.
- **OCR is not implemented.** Scanned PDFs are refused with an explanation.
- **SLMFlow's own README** states that its performance advantages are not
  established. Nothing in this app claims otherwise.

---

## Configuration

All optional — copy `.env.example` to `.env` and edit. The ones you are most
likely to touch:

| Variable | Meaning |
|---|---|
| `OLLAMA_HOST` | Ollama daemon URL (default `http://localhost:11434`) |
| `SLMFLOW_STRATEGY` | `single` (default), `cascade`, `slm_mux`, `adaptive`, `agent_forest` |
| `SLMFLOW_ANSWER_MODEL` | pin the answer step's model, or set to `router` to let the router decide |
| `SLMFLOW_MAX_MODELS` | how many local models to register (default 3) |
| `SLMFLOW_VRAM_BUDGET_GB` / `SLMFLOW_RAM_BUDGET_GB` | override the memory budget SLMFlow probes from your machine |
| `SLMFLOW_MOCK` | `1` to use SLMFlow's clearly-labelled mock backend |

---

## Project layout

```
backend/
  main.py          FastAPI app: upload, ask, status endpoints + static UI serving
  engine.py        SLMFlow integration: registry, pipeline, log capture, trace
  documents.py     PDF validation, text extraction, chunking, keyword retrieval
  data/            uploaded PDFs and SLMFlow's JSONL run trace (gitignored)
frontend/
  src/App.jsx      layout and state
  src/components/  upload card, chat panel, status card, execution trace
  src/bits.jsx     small shared UI pieces and formatters
sample/
  sample_medical_report.pdf     a small made-up report to try the demo with
start.ps1          create venv, install everything, build the UI, start the app
requirements.txt   backend dependencies (SLMFlow is installed separately)
.env.example       every configuration variable, with comments
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `No model configured` in the header | Start Ollama (`ollama serve`) and pull a model, then click **Re-scan** on the status card |
| `ResourceExhausted` in the trace | Your budget is too small for the registered models. Raise `SLMFLOW_VRAM_BUDGET_GB` / `SLMFLOW_RAM_BUDGET_GB`, or lower `SLMFLOW_MAX_MODELS` |
| Answers say the document has no information | Try a larger model (set the answer-step model to `llama3.2:3b`), or a question the document really answers |
| `This PDF looks like a scan` | The file is image-only. Run it through an OCR tool and upload the text-based result |
| Port 8000 already in use | `.\start.ps1 -Port 9000` then open `http://127.0.0.1:9000` |
| Blank page at `/` | Build the UI: `cd frontend; npm install; npm run build` |
