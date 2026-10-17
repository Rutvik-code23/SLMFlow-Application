import React, { useCallback, useEffect, useState } from 'react'
import { askQuestion, getStatus, refreshModels, setConfig, uploadDocument } from './api.js'
import ChatPanel from './components/ChatPanel.jsx'
import SlmflowStatus from './components/SlmflowStatus.jsx'
import TracePanel from './components/TracePanel.jsx'
import UploadPanel from './components/UploadPanel.jsx'

let nextId = 1

export default function App() {
  const [status, setStatus] = useState(null)
  const [doc, setDoc] = useState(null)
  const [messages, setMessages] = useState([])
  const [run, setRun] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [asking, setAsking] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [askError, setAskError] = useState('')

  const busy = uploading || asking

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await getStatus())
    } catch (err) {
      setStatus({ _error: err.message })
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  async function handleUpload(file) {
    setUploadError('')
    setAskError('')
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setUploadError('Only PDF files are accepted. Choose a .pdf file.')
      return
    }
    setUploading(true)
    try {
      const record = await uploadDocument(file)
      setDoc(record)
      setMessages([])
      setRun(null)
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
    }
  }

  function handleClear() {
    setDoc(null)
    setMessages([])
    setRun(null)
    setUploadError('')
    setAskError('')
  }

  async function handleAsk(question) {
    setAskError('')
    setAsking(true)
    setMessages((m) => [...m, { id: nextId++, role: 'user', text: question }])
    try {
      const result = await askQuestion(doc.id, question)
      setRun(result)
      const model = result.steps?.length
        ? result.steps[result.steps.length - 1].model_id
        : null
      setMessages((m) => [
        ...m,
        {
          id: nextId++,
          role: 'ai',
          text:
            result.answer && String(result.answer).trim()
              ? String(result.answer)
              : result.abstained
                ? `SLMFlow declined to answer (${result.abstention_reason || 'low confidence'}).`
                : 'No answer was produced.',
          confidence: result.confidence,
          abstained: Boolean(result.abstained),
          time: result.response_time_s,
          model,
          mock: Boolean(result.mock),
        },
      ])
    } catch (err) {
      setAskError(err.message)
      setMessages((m) => [
        ...m,
        {
          id: nextId++,
          role: 'ai',
          text: `Request failed: ${err.message}`,
          abstained: true,
          time: undefined,
        },
      ])
    } finally {
      setAsking(false)
      loadStatus()
    }
  }

  async function handleConfig(body) {
    setAsking(true)
    try {
      setStatus(await setConfig(body))
      setRun(null)
    } catch (err) {
      setAskError(err.message)
    } finally {
      setAsking(false)
    }
  }

  async function handleRefresh() {
    setAsking(true)
    try {
      setStatus(await refreshModels())
    } catch (err) {
      setAskError(err.message)
    } finally {
      setAsking(false)
    }
  }

  if (status && status._error) {
    return (
      <div className="layout">
        <div className="col">
          <div className="card">
            <div className="card-body">
              <h2 className="card-title">Backend not reachable</h2>
              <p style={{ marginTop: 8 }}>
                Could not load <code>/api/status</code>: {status._error}
              </p>
              <p className="file-sub">
                Start the backend with <code>./start.ps1</code>, or manually run{' '}
                <code>.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000</code>{' '}
                from the project folder, then reload this page.
              </p>
              <button className="btn btn-primary" onClick={loadStatus}>
                Try again
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  const sf = status?.slmflow || {}
  const backend = status?.backend || {}
  const ready = sf.import_ok && backend.available && (backend.registered_models || []).length > 0

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">SM</div>
          <div>
            <h1>SLMFlow Medical AI</h1>
            <p>Ask questions about a local medical PDF — orchestrated by SLMFlow</p>
          </div>
        </div>
        <div className="topbar-right">
          {sf.mock && <span className="pill mock">MOCK BACKEND</span>}
          <span className={`pill ${ready ? 'ok' : 'warn'}`}>
            <span className="pill-dot" />
            {ready ? 'Model backend ready' : 'No model configured'}
          </span>
          <span className="pill">
            <span className="pill-dot" />
            slmflow {sf.version || '…'}
          </span>
        </div>
      </header>

      <main className="layout">
        <div className="col">
          <UploadPanel
            doc={doc}
            busy={uploading}
            error={uploadError}
            onUpload={handleUpload}
            onClear={handleClear}
          />
          <SlmflowStatus
            status={status}
            busy={busy}
            onConfig={handleConfig}
            onRefresh={handleRefresh}
          />
        </div>

        <div className="col">
          <ChatPanel
            doc={doc}
            messages={messages}
            busy={asking}
            error={askError}
            onAsk={handleAsk}
          />
          <TracePanel run={run} busy={asking} />
        </div>
      </main>

      <footer className="footer-note">
        Everything runs locally: the PDF is read on this machine, and inference happens
        in a local <strong>Ollama</strong> model through the <strong>SLMFlow</strong>{' '}
        orchestration library. Answers are only as good as the small local model and the
        extracted text — no figure here is independently verified.
      </footer>
    </>
  )
}
