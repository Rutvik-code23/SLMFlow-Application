import React from 'react'
import {
  Badge,
  Card,
  CATEGORIES,
  EmptyState,
  ScoreBars,
  Spinner,
  fmtBytes,
  fmtNumber,
  fmtSeconds,
} from '../bits.jsx'

/* The "how did the backend actually work" panel. Everything rendered here is
   either an SLMFlow log event, an SLMFlow schedule/trace field, or a step the
   application itself took. Nothing is inferred or embellished. */
export default function TracePanel({ run, busy }) {
  if (!run && !busy) {
    return (
      <Card
        title="3 · SLMFlow execution trace"
        subtitle="Scheduling, routing, residency and every step, in order."
      >
        <EmptyState title="Nothing has run yet">
          Ask a question and this panel fills up with the exact decisions SLMFlow
          made: the schedule it planned, the model the router picked, what it had
          to load or evict, and the confidence it scored the answer with.
        </EmptyState>
      </Card>
    )
  }

  if (!run) {
    return (
      <Card
        title="3 · SLMFlow execution trace"
        subtitle="Scheduling, routing, residency and every step, in order."
      >
        <Spinner label="Waiting for the pipeline…" />
      </Card>
    )
  }

  const timeline = run.timeline || []
  const plan = run.plan
  const steps = run.steps || []
  const trace = run.trace
  const retrieval = run.retrieval || {}
  const routeEvents = (run.raw_events || []).filter((e) => e.event === 'route')

  return (
    <Card
      title="3 · SLMFlow execution trace"
      subtitle="Every decision the orchestrator made, in the order it made it."
      actions={
        <>
          {run.mock && <Badge tone="red">MOCK RUN</Badge>}
          <Badge tone={run.ok ? 'green' : run.abstained ? 'amber' : 'red'}>
            {run.ok ? 'SUCCEEDED' : run.abstained ? 'ABSTAINED' : 'FAILED'}
          </Badge>
        </>
      }
    >
      {/* ---- headline numbers ---- */}
      <div className="trace-grid">
        <Tile k="Response time" v={fmtSeconds(run.response_time_s)} />
        <Tile k="Confidence" v={run.confidence === null ? 'not scored' : fmtNumber(run.confidence, 2)} />
        <Tile k="Model swaps" v={trace ? `${trace.total_swaps}` : '—'} />
        <Tile k="Time loading models" v={trace ? fmtSeconds(trace.swap_seconds) : '—'} />
        <Tile k="Generations" v={trace ? `${trace.total_generations}` : '—'} />
        <Tile k="Output tokens" v={trace ? `${trace.output_tokens}` : '—'} />
      </div>

      {run.abstained && (
        <div className="warn-note" style={{ marginTop: 12 }}>
          SLMFlow <strong>abstained</strong> (reason: {run.abstention_reason || 'unspecified'}).
          It declined to return an answer rather than guess.
        </div>
      )}
      {run.error && (
        <div className="error-note" style={{ marginTop: 12 }}>
          <strong>{run.error_type}:</strong> {run.error}
          {run.install_hint && (
            <>
              {' '}
              <br />
              Hint: <code>{run.install_hint}</code>
            </>
          )}
        </div>
      )}

      {/* ---- retrieval ---- */}
      <div className="section-label">Context selection</div>
      <p className="tl-detail">
        {retrieval.chunks_total} chunk(s) of the document, {retrieval.chunk_size}{' '}
        characters each; sent {retrieval.selected?.length || 0} of them (top{' '}
        {retrieval.top_k}). Method: <strong>{retrieval.strategy}</strong>.
        <br />
        {retrieval.note}
      </p>
      {retrieval.selected && retrieval.selected.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: '#627d98' }}>
            Show the passages sent to the model
          </summary>
          {retrieval.selected.map((c) => (
            <div key={c.index} style={{ marginTop: 8 }}>
              <Badge tone="blue">
                chunk {c.index + 1} · score {Number(c.score).toFixed(3)}
              </Badge>
              <div className="text-preview" style={{ maxHeight: 140, marginTop: 4 }}>
                {c.text}
              </div>
            </div>
          ))}
        </details>
      )}

      {/* ---- scheduler plan ---- */}
      {plan && (
        <>
          <div className="section-label">
            Scheduler — <code>{plan.planner}</code>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Planned model</th>
                  <th>Load before</th>
                  <th>Evict before</th>
                </tr>
              </thead>
              <tbody>
                {plan.entries.map((e) => (
                  <tr key={e.step}>
                    <td>{e.step}</td>
                    <td className="mono">{e.model_id}</td>
                    <td>{e.load_before ? <Badge tone="amber">LOAD</Badge> : <Badge tone="green">REUSE</Badge>}</td>
                    <td className="mono">
                      {e.evict_before.length ? e.evict_before.join(', ') : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="tl-detail" style={{ marginTop: 6 }}>
            Predicted loads: <strong>{plan.predicted_loads}</strong>. Predicted seconds:{' '}
            <strong>{plan.predicted_seconds === null ? 'not measured' : fmtSeconds(plan.predicted_seconds)}</strong>
            . Predicted quality:{' '}
            <strong>{plan.predicted_quality === null ? 'not measured' : fmtNumber(plan.predicted_quality, 4)}</strong>.
            SLMFlow leaves these as <code>null</code> when the model cards have not
            been profiled on this machine — it will not invent a number.
          </p>
        </>
      )}

      {/* ---- router decisions ---- */}
      {routeEvents.length > 0 && (
        <>
          <div className="section-label">Router decisions</div>
          {routeEvents.map((e, i) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <div className="tl-top">
                <Badge tone="violet">ROUTE</Badge>
                <span className="tl-title">
                  step “{e.data.step}” → {e.data.chosen}
                </span>
                <Badge tone={e.data.warm ? 'green' : 'amber'}>
                  {e.data.warm ? 'ALREADY RESIDENT' : 'COLD — NEEDED A LOAD'}
                </Badge>
              </div>
              <ScoreBars scores={e.data.scores} />
            </div>
          ))}
          <p className="tl-detail">
            Scores come from <code>HeuristicRouter</code>: measured accuracy, minus a
            penalty for cards that were never profiled on this machine, plus a small
            bonus for a model that is already resident, minus a size penalty. These
            three models have no measured accuracy, so the unprofiled penalty applies
            to all of them and the size term decides.
          </p>
        </>
      )}

      {/* ---- step results ---- */}
      {steps.length > 0 && (
        <>
          <div className="section-label">Steps actually executed</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Model</th>
                  <th>Strategy</th>
                  <th>Gens</th>
                  <th>In / out tokens</th>
                  <th>Latency</th>
                  <th>Conf.</th>
                  <th>Swaps</th>
                  <th>Wall</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {steps.map((s) => {
                  const inTok = s.generations.reduce((a, g) => a + g.prompt_tokens, 0)
                  const outTok = s.generations.reduce((a, g) => a + g.output_tokens, 0)
                  const lat = s.generations.reduce((a, g) => a + g.latency_s, 0)
                  return (
                    <tr key={s.step}>
                      <td>{s.step}</td>
                      <td className="mono">{s.model_id || '—'}</td>
                      <td>{s.strategy}</td>
                      <td className="num">{s.generations.length}</td>
                      <td className="num">
                        {inTok} / {outTok}
                      </td>
                      <td className="num">{fmtSeconds(lat)}</td>
                      <td className="num">{s.confidence === null ? '—' : fmtNumber(s.confidence, 2)}</td>
                      <td className="num">
                        {s.swaps}
                        {s.swap_seconds > 0 ? ` (${fmtSeconds(s.swap_seconds)})` : ''}
                      </td>
                      <td className="num">{fmtSeconds(s.wall_s)}</td>
                      <td>
                        {s.error ? (
                          <Badge tone="red">ERROR</Badge>
                        ) : s.abstained ? (
                          <Badge tone="amber">ABSTAINED</Badge>
                        ) : (
                          <Badge tone="green">OK</Badge>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {steps.some((s) => s.confidence_signals && Object.keys(s.confidence_signals).length > 0) && (
            <p className="tl-detail" style={{ marginTop: 6 }}>
              Confidence signals:{' '}
              {steps
                .filter((s) => s.confidence_signals && Object.keys(s.confidence_signals).length)
                .map((s) => `${s.step}: ${JSON.stringify(s.confidence_signals)}`)
                .join(' · ')}
            </p>
          )}
        </>
      )}

      {/* ---- ordered timeline ---- */}
      <div className="section-label">Everything, in order</div>
      <div className="timeline">
        {timeline.map((item) => {
          const meta = CATEGORIES[item.category] || CATEGORIES.slmflow
          const cls = `tl-item ${
            item.category === 'result'
              ? 'is-result'
              : item.category === 'warning'
                ? 'is-warning'
                : item.source === 'slmflow'
                  ? 'is-slmflow'
                  : ''
          }`
          return (
            <div key={item.n} className={cls}>
              <div className="tl-rail">
                <div className="tl-num">{item.n}</div>
                <div className="tl-line" />
              </div>
              <div className="tl-body">
                <div className="tl-top">
                  <Badge tone={meta.tone}>{meta.label}</Badge>
                  <Badge tone={item.source === 'slmflow' ? 'blue' : 'slate'}>
                    {item.source === 'slmflow' ? 'slmflow' : 'app'}
                  </Badge>
                  <span className="tl-title">{item.title}</span>
                </div>
                <div className="tl-detail">{item.detail}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* ---- run trace ---- */}
      {trace && (
        <>
          <div className="section-label">
            SLMFlow <code>RunTrace</code>
          </div>
          <div className="trace-grid">
            <Tile k="run id" v={trace.run_id} mono />
            <Tile k="pipeline" v={trace.pipeline} mono />
            <Tile k="device" v={trace.device} mono />
            <Tile k="wall time" v={fmtSeconds(trace.wall_s)} />
            <Tile k="peak VRAM" v={fmtBytes(trace.peak_vram_bytes)} />
            <Tile k="peak RAM" v={fmtBytes(trace.peak_ram_bytes)} />
            <Tile k="config digest" v={trace.config_digest} mono />
            <Tile k="models used" v={trace.models_used.join(', ') || '—'} mono />
          </div>
          <p className="tl-detail" style={{ marginTop: 8 }}>
            This is the same object SLMFlow writes to <code>backend/data/slmflow_runs.jsonl</code>{' '}
            via its <code>TraceWriter</code>.
          </p>
        </>
      )}
    </Card>
  )
}

function Tile({ k, v, mono }) {
  return (
    <div className="trace-tile">
      <div className="t-k">{k}</div>
      <div className={`t-v ${mono ? 'mono' : ''}`}>{v}</div>
    </div>
  )
}
