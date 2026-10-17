import React from 'react'

/* ------------------------------------------------------------------ *
 * Small shared presentational pieces + formatters.
 * Every number rendered here comes straight from the backend, which
 * takes it from SLMFlow or from Ollama. Nothing is rounded into a
 * claim the data does not support.
 * ------------------------------------------------------------------ */

export function fmtBytes(value) {
  if (value === null || value === undefined) return '—'
  let n = Number(value)
  if (Number.isNaN(n)) return '—'
  if (n <= 0) return '0 B'
  const units = ['B', 'kB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1000 && i < units.length - 1) {
    n /= 1000
    i += 1
  }
  return `${i === 0 ? n.toFixed(0) : n.toFixed(2)} ${units[i]}`
}

export function fmtSeconds(value) {
  if (value === null || value === undefined) return '—'
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return `${n.toFixed(2)} s`
}

export function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined) return 'not measured'
  const n = Number(value)
  if (Number.isNaN(n)) return 'not measured'
  return n.toFixed(digits)
}

export function shortModel(name) {
  if (!name) return '—'
  return name.length > 30 ? `${name.slice(0, 27)}…` : name
}

/* Timeline category metadata. The backend sends the category; these are
   only labels and colours, never invented content. */
export const CATEGORIES = {
  ingest: { label: 'INGEST', tone: 'slate' },
  retrieve: { label: 'RETRIEVE', tone: 'blue' },
  config: { label: 'CONFIG', tone: 'slate' },
  plan: { label: 'SCHEDULE', tone: 'violet' },
  route: { label: 'ROUTE', tone: 'violet' },
  residency: { label: 'RESIDENCY', tone: 'amber' },
  strategy: { label: 'STRATEGY', tone: 'violet' },
  step: { label: 'STEP', tone: 'blue' },
  result: { label: 'RESULT', tone: 'green' },
  warning: { label: 'WARNING', tone: 'red' },
  slmflow: { label: 'SLMFLOW', tone: 'slate' },
}

export function Badge({ tone = 'slate', children }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function Card({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  )
}

export function Spinner({ label = 'Working…' }) {
  return (
    <span className="spinner-wrap">
      <span className="spinner" aria-hidden="true" />
      <span className="spinner-label">{label}</span>
    </span>
  )
}

export function EmptyState({ title, children }) {
  return (
    <div className="empty">
      <div className="empty-mark" aria-hidden="true">
        ▢
      </div>
      <p className="empty-title">{title}</p>
      {children && <p className="empty-text">{children}</p>}
    </div>
  )
}

export function ErrorNote({ children }) {
  if (!children) return null
  return (
    <div className="error-note" role="alert">
      <strong>Problem:</strong> {children}
    </div>
  )
}

export function KV({ k, v, mono = false }) {
  return (
    <div className="kv">
      <span className="kv-k">{k}</span>
      <span className={`kv-v ${mono ? 'mono' : ''}`}>{v}</span>
    </div>
  )
}

/* A small bar chart of router scores. Bars are relative to the best score
   in the row; the numbers themselves are printed next to them. */
export function ScoreBars({ scores }) {
  if (!scores || !Object.keys(scores).length) return null
  const entries = Object.entries(scores)
  const values = entries.map(([, v]) => Number(v))
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 0)
  const span = max - min || 1
  return (
    <ul className="scores">
      {entries.map(([model, value]) => {
        const pct = 6 + (94 * (Number(value) - min)) / span
        return (
          <li key={model} className="score-row">
            <span className="score-model mono">{model}</span>
            <span className="score-track">
              <span className="score-fill" style={{ width: `${pct}%` }} />
            </span>
            <span className="score-value mono">{Number(value).toFixed(4)}</span>
          </li>
        )
      })}
    </ul>
  )
}
