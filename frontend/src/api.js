// Thin API client for the FastAPI backend. All calls are same-origin.

async function handle(response) {
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok) {
    const detail =
      (payload && (payload.detail || payload.error)) ||
      `Request failed (HTTP ${response.status})`
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    err.status = response.status
    err.payload = payload
    throw err
  }
  return payload
}

export async function getStatus() {
  return handle(await fetch('/api/status'))
}

export async function refreshModels() {
  return handle(await fetch('/api/status/refresh', { method: 'POST' }))
}

export async function setConfig(body) {
  return handle(
    await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

export async function uploadDocument(file) {
  const form = new FormData()
  form.append('file', file)
  return handle(await fetch('/api/documents', { method: 'POST', body: form }))
}

export async function askQuestion(documentId, question) {
  return handle(
    await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ document_id: documentId, question }),
    }),
  )
}
