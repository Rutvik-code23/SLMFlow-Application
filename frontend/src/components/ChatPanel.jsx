import React, { useEffect, useRef, useState } from 'react'
import { Badge, Card, EmptyState, ErrorNote, Spinner, fmtSeconds } from '../bits.jsx'

const SUGGESTIONS = [
  'What is the primary diagnosis in this report?',
  'Summarize the medical report.',
  'Which lab results are outside the normal range?',
  'List the prescribed medications and their dosages.',
  'Are there any abnormal values worth reviewing?',
]

/* Feature B: ask questions about the uploaded document. */
export default function ChatPanel({ doc, messages, busy, error, onAsk }) {
  const [draft, setDraft] = useState('')
  const scrollRef = useRef(null)

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, busy])

  const canAsk = Boolean(doc && doc.readable && !busy)

  function submit(text) {
    const question = (text || '').trim()
    if (!question || !canAsk) return
    setDraft('')
    onAsk(question)
  }

  return (
    <Card
      title="2 · Ask about the document"
      subtitle={
        doc
          ? `Context: ${doc.filename}`
          : 'Upload a PDF first — this panel unlocks once there is text.'
      }
    >
      <ErrorNote>{error}</ErrorNote>

      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 && !busy && (
          <EmptyState title={doc ? 'Ask your first question' : 'No document yet'}>
            {doc
              ? 'Every answer is grounded in the text extracted from your PDF. If the answer is not in the document, SLMFlow will say so rather than guess.'
              : 'Upload a lab report, prescription or discharge summary on the left to get started.'}
          </EmptyState>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`msg ${m.role === 'user' ? 'msg-user' : 'msg-ai'}`}>
            <span className="msg-role">{m.role === 'user' ? 'You' : 'SLMFlow'}</span>
            <div className={`bubble ${m.abstained ? 'abstained' : ''}`}>{m.text}</div>
            {m.role === 'ai' && (
              <div className="msg-foot">
                {m.mock && <Badge tone="red">MOCK</Badge>}
                {m.abstained && <Badge tone="amber">ABSTAINED</Badge>}
                {m.confidence !== null && m.confidence !== undefined && (
                  <span>confidence {Number(m.confidence).toFixed(2)}</span>
                )}
                {m.time !== undefined && <span>· {fmtSeconds(m.time)}</span>}
                {m.model && <span>· {m.model}</span>}
              </div>
            )}
          </div>
        ))}

        {busy && (
          <div className="msg msg-ai">
            <span className="msg-role">SLMFlow</span>
            <div className="bubble">
              <Spinner label="Planning, routing and generating — watch the trace below." />
            </div>
          </div>
        )}
      </div>

      <div className="chips">
        {SUGGESTIONS.map((q) => (
          <button key={q} className="chip" disabled={!canAsk} onClick={() => submit(q)}>
            {q}
          </button>
        ))}
      </div>

      <div className="composer">
        <input
          type="text"
          value={draft}
          placeholder={
            doc && !doc.readable
              ? 'Disabled: no readable text was extracted from this PDF'
              : doc
                ? 'Ask a question about the document…'
                : 'Upload a PDF to start asking questions'
          }
          disabled={!canAsk}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') submit(draft)
          }}
        />
        <button
          className="btn btn-primary"
          disabled={!canAsk || draft.trim().length < 4}
          onClick={() => submit(draft)}
        >
          Ask
        </button>
      </div>
    </Card>
  )
}
