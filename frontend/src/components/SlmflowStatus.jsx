import React from 'react'
import { Card, KV, Spinner, fmtBytes, fmtNumber, fmtSeconds } from '../bits.jsx'

const STRATEGIES = [
  { id: 'single', label: 'single — one model, one greedy sample' },
  { id: 'cascade', label: 'cascade — escalate only when confidence is low' },
  { id: 'slm_mux', label: 'slm_mux — sample k times, keep the majority' },
  { id: 'adaptive', label: 'adaptive — stop sampling once sure' },
  { id: 'agent_forest', label: 'agent_forest — vote across several models' },
]

/* Feature C + D: what SLMFlow is doing, and how to switch a model on. */
export default function SlmflowStatus({ status, busy, onConfig, onRefresh }) {
  if (!status) {
    return (
      <Card title="Powered by SLMFlow">
        <Spinner label="Reading SLMFlow status…" />
      </Card>
    )
  }

  const sf = status.slmflow || {}
  const backend = status.backend || {}
  const config = status.config || {}
  const last = status.last_request
  const residency = status.residency
  const budget = config.budget || {}
  const models = backend.registered_models || []
  const ready = sf.import_ok && backend.available && models.length > 0

  return (
    <Card
      title="Powered by SLMFlow"
      subtitle={
        sf.mock
          ? 'Mock backend active — these are scripted strings, not model output.'
          : 'Live values read from the installed package.'
      }
      actions={
        <button className="btn" onClick={onRefresh} disabled={busy} title="Re-scan Ollama for models">
          Re-scan
        </button>
      }
    >
      <div className="section-label">Package</div>
      <KV k="slmflow version" v={sf.version} mono />
      <KV
        k="imported"
        v={sf.import_ok ? 'yes' : `no — ${sf.import_error || 'unknown error'}`}
      />
      <KV k="mode" v={sf.mock ? 'MOCK (scripted, not inference)' : 'real inference'} />

      <div className="section-label">Pipeline configuration</div>
      <KV k="strategy" v={config.strategy} />
      <KV
        k="strategy parameters"
        v={
          config.strategy === 'single'
            ? 'k=1, temperature=0 (greedy)'
            : `k=${config.k}, temperature=${config.temperature}`
        }
      />
      <KV k="router" v={config.router} />
      <KV k="scheduler" v={config.scheduler} />
      <KV k="abstention threshold" v={fmtNumber(config.threshold, 2)} />
      <KV k="max output tokens" v={config.max_output_tokens} />
      <KV k="answer-step model" v={config.answer_model || 'chosen by the router'} />

      <div className="section-label">Model backend</div>
      <KV k="backend" v={backend.name} />
      <KV k="daemon" v={backend.url} mono />
      <KV
        k="reachable"
        v={backend.available ? 'yes' : 'no'}
      />
      <KV
        k="models registered"
        v={`${models.length}`}
      />
      {models.map((m) => (
        <KV
          key={m.model_id}
          k={m.model_id}
          v={`${fmtBytes(m.declared_vram_bytes)} declared · ${m.profiled ? 'profiled' : 'not profiled'}`}
          mono
        />
      ))}

      <div className="section-label">Memory budget (per tier)</div>
      <KV k="VRAM ceiling" v={fmtBytes(budget.vram_bytes)} mono />
      <KV k="RAM ceiling" v={fmtBytes(budget.ram_bytes)} mono />

      {residency && (
        <>
          <div className="section-label">Live residency</div>
          <KV
            k="models resident"
            v={
              residency.resident_models.length
                ? residency.resident_models.join(', ')
                : 'none'
            }
            mono
          />
          <KV
            k="resident now"
            v={`${fmtBytes(residency.vram_bytes)} VRAM · ${fmtBytes(residency.ram_bytes)} RAM`}
            mono
          />
          <KV
            k="loads / evictions"
            v={`${residency.ledger.loads} / ${residency.ledger.evictions}`}
          />
          <KV k="time spent loading" v={fmtSeconds(residency.ledger.load_seconds)} />
        </>
      )}

      <div className="section-label">Last request</div>
      {last ? (
        <>
          <KV
            k="result"
            v={last.ok ? 'succeeded' : last.abstained ? 'abstained' : 'failed'}
          />
          <KV k="response time" v={fmtSeconds(last.response_time_s)} />
          <KV k="confidence" v={last.confidence === null ? 'not scored' : fmtNumber(last.confidence, 2)} />
          {last.abstention_reason && <KV k="abstention reason" v={last.abstention_reason} />}
          {last.error && <KV k="error" v={last.error} />}
        </>
      ) : (
        <p className="file-sub" style={{ marginTop: 6 }}>
          No question has been asked yet.
        </p>
      )}

      <div className="section-label">Switch execution strategy</div>
      <label className="field" htmlFor="strategy-select">
        Strategies ship with SLMFlow. Sampling ones are slower but produce a real
        self-consistency confidence.
      </label>
      <select
        id="strategy-select"
        value={config.strategy}
        disabled={busy}
        onChange={(e) => onConfig({ strategy: e.target.value })}
      >
        {STRATEGIES.map((s) => (
          <option key={s.id} value={s.id}>
            {s.label}
          </option>
        ))}
      </select>

      {models.length > 0 && (
        <>
          <label className="field" style={{ marginTop: 10 }} htmlFor="model-select">
            Model for the answer step. By default the largest registered model is
            pinned here; choose “router decides” to let SLMFlow score every model
            instead.
          </label>
          <select
            id="model-select"
            value={config.answer_model || ''}
            disabled={busy}
            onChange={(e) => onConfig({ answer_model: e.target.value })}
          >
            <option value="">— router decides —</option>
            {models.map((m) => (
              <option key={m.model_id} value={m.model_id}>
                {m.model_id}
              </option>
            ))}
          </select>
        </>
      )}

      <div className="section-label">How to enable real AI answers</div>
      {ready ? (
        <div className="info-note">
          A local model backend is available, so the answers above are real
          inference from <strong>{backend.name}</strong> using{' '}
          <strong>{models.map((m) => m.model_id).join(', ')}</strong>.
        </div>
      ) : (
        <>
          <div className="setup-box">{status.setup}</div>
          <p className="file-sub" style={{ marginTop: 8 }}>
            Until a model is available the app still starts, but questions are refused
            instead of returning fake answers.
          </p>
        </>
      )}

      {status.describe_error && (
        <div className="warn-note" style={{ marginTop: 10 }}>
          SLMFlow could not describe the current pipeline: {status.describe_error}
        </div>
      )}
      {status.device_error && (
        <div className="warn-note" style={{ marginTop: 10 }}>
          Device probe failed: {status.device_error}
        </div>
      )}
      {status.device && (
        <div style={{ marginTop: 10 }}>
          <div className="section-label">Probed device</div>
          <KV k="tier" v={status.device.tier} />
          <KV k="GPU" v={status.device.gpu_model || 'none detected'} />
          <KV k="CPU" v={status.device.cpu_model} />
          <KV k="total RAM" v={fmtBytes(status.device.total_ram_bytes)} mono />
          <KV k="total VRAM" v={fmtBytes(status.device.total_vram_bytes)} mono />
          <p className="file-sub" style={{ marginTop: 6 }}>
            Probed by <code>slmflow.probe()</code> — these are the numbers SLMFlow
            derives its default budget from.
          </p>
        </div>
      )}
    </Card>
  )
}
