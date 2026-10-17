import React, { useRef, useState } from 'react'
import { Card, ErrorNote, Spinner } from '../bits.jsx'

/* Feature A: upload a PDF, extract its text locally, show it. */
export default function UploadPanel({ doc, busy, error, onUpload, onClear }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function handleFiles(files) {
    const file = files && files[0]
    if (file) onUpload(file)
  }

  return (
    <Card
      title="1 · Medical document"
      subtitle="PDF stays on this machine. Nothing is uploaded anywhere else."
    >
      <ErrorNote>{error}</ErrorNote>

      {!doc && (
        <>
          <div
            className={`drop ${dragging ? 'dragging' : ''}`}
            onClick={() => inputRef.current && inputRef.current.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              handleFiles(e.dataTransfer.files)
            }}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
            }}
          >
            {busy ? (
              <Spinner label="Extracting text from the PDF…" />
            ) : (
              <>
                <strong>Drop a lab report, prescription or discharge summary here</strong>
                or click to choose a file
                <div className="drop-hint">PDF only · size limit is set by the server</div>
              </>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            style={{ display: 'none' }}
            onChange={(e) => {
              handleFiles(e.target.files)
              e.target.value = ''
            }}
          />
        </>
      )}

      {doc && (
        <>
          <div className="file-row">
            <div className="file-meta">
              <div className="file-name">{doc.filename}</div>
              <div className="file-sub">
                {(doc.bytes / 1024).toFixed(1)} kB · {doc.pages} page
                {doc.pages === 1 ? '' : 's'} · {doc.chars.toLocaleString()} characters
                extracted in {doc.extract_time_s}s
              </div>
            </div>
            <button className="btn btn-ghost" onClick={onClear} disabled={busy}>
              Remove
            </button>
          </div>

          {doc.warnings && doc.warnings.length > 0 && (
            <div className="warn-note">
              {doc.warnings.map((w, i) => (
                <div key={i}>{w}</div>
              ))}
            </div>
          )}

          <div className="section-label">Extracted text</div>
          {doc.readable ? (
            <>
              <div className="text-meta">
                <span>
                  <strong>{doc.chars.toLocaleString()}</strong> characters
                </span>
                <span>
                  <strong>{doc.images}</strong> embedded image{doc.images === 1 ? '' : 's'}
                </span>
              </div>
              <div className="text-preview">{doc.text}</div>
            </>
          ) : (
            <div className="warn-note">
              No readable text could be extracted, so questions are disabled for this
              document. This app does <strong>not</strong> include OCR. Run the file
              through an OCR tool and upload the text-based result instead.
            </div>
          )}
        </>
      )}
    </Card>
  )
}
