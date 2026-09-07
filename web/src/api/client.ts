// REST + SSE client helpers.

async function handle(resp: Response) {
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok && !('ok' in data)) {
    throw new Error(`HTTP ${resp.status}`)
  }
  return data
}

export const api = {
  get: (path: string) => fetch(path).then(handle),
  post: (path: string, body?: unknown) =>
    fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(handle),
  put: (path: string, body?: unknown) =>
    fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(handle),
}

/** Open an SSE endpoint; returns a closer function. */
export function openStream(
  path: string,
  onEvent: (type: string, data: Record<string, unknown>) => void,
  onDone?: () => void,
): () => void {
  const es = new EventSource(path)
  es.onmessage = (ev) => {
    try {
      const payload = JSON.parse(ev.data)
      onEvent(payload.type ?? 'message', payload)
    } catch {
      /* ignore malformed lines */
    }
  }
  es.addEventListener('done', () => {
    es.close()
    onDone?.()
  })
  es.onerror = () => {
    /* EventSource auto-reconnects; server closes cleanly on done */
  }
  return () => es.close()
}
