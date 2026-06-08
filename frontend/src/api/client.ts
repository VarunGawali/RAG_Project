/**
 * Thin API client for the Contract360 FastAPI backend.
 *
 * Base URL is read from the VITE_API_BASE_URL env variable so it works
 * for both local dev (http://localhost:8000) and deployed environments.
 * Falls back to same-origin /api for when both are served together.
 */

import type { ChatSession, Message } from '../types'

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api'

// The user-id header used by the demo.  Replace with real auth token later.
const DEFAULT_USER = 'default_user'

function headers(userId = DEFAULT_USER): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-User-Id': userId,
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ?? detail
    } catch {
      // ignore parse error
    }
    throw new Error(`API ${res.status}: ${detail}`)
  }
  if (res.status === 204) return undefined as unknown as T
  return res.json() as Promise<T>
}

// ──────────────────────────────────────────────
// Session API
// ──────────────────────────────────────────────

export interface CreateSessionPayload {
  contract_filter?: string | null
}

export interface SessionSummary {
  id: string
  title: string
  contractFilter: string | null
  createdAt: string
  updatedAt: string
  previewText?: string
}

export interface AskPayload {
  question: string
  top?: number
  route_override?: string
  return_context?: boolean
  contract_ids?: string[] | null
}

export interface AskResult {
  session_id: string
  message_id: string
  route: string
  reason: string
  rewritten_query?: string
  answer: string
  citations?: import('../types').Citation[]
  follow_up_suggestions?: string[]
  context?: string
}

// SSE event shapes
export interface StreamDelta  { type: 'delta';  content: string }
export interface StreamDone   {
  type: 'done'
  message_id: string
  route: string
  reason: string
  rewritten_query?: string
  citations: import('../types').Citation[]
  follow_up_suggestions: string[]
}
export interface StreamError  { type: 'error';  detail: string }
export type StreamEvent = StreamDelta | StreamDone | StreamError

/**
 * Streaming ask — yields SSE events as they arrive.
 * Caller receives (onDelta, onDone, onError) callbacks.
 */
export async function askQuestionStream(
  sessionId: string,
  payload: AskPayload,
  onDelta: (token: string) => void,
  onDone: (done: StreamDone) => void,
  onError: (detail: string) => void,
  userId?: string,
): Promise<void> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/ask/stream`, {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify(payload),
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    onError(`API ${res.status}: ${detail}`)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      try {
        const event: StreamEvent = JSON.parse(trimmed)
        if (event.type === 'delta')  onDelta(event.content)
        else if (event.type === 'done')  onDone(event)
        else if (event.type === 'error') onError(event.detail)
      } catch { /* malformed line — ignore */ }
    }
  }
}

export async function createSession(
  payload: CreateSessionPayload,
  userId?: string,
): Promise<ChatSession> {
  const res = await fetch(`${BASE}/sessions`, {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify(payload),
  })
  return handleResponse<ChatSession>(res)
}

export async function listSessions(userId?: string): Promise<SessionSummary[]> {
  const res = await fetch(`${BASE}/sessions`, { headers: headers(userId) })
  return handleResponse<SessionSummary[]>(res)
}

export async function getSession(
  sessionId: string,
  userId?: string,
): Promise<ChatSession> {
  const res = await fetch(`${BASE}/sessions/${sessionId}`, {
    headers: headers(userId),
  })
  return handleResponse<ChatSession>(res)
}

export async function getHistory(
  sessionId: string,
  userId?: string,
): Promise<Message[]> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/history`, {
    headers: headers(userId),
  })
  return handleResponse<Message[]>(res)
}

export async function deleteSession(
  sessionId: string,
  userId?: string,
): Promise<void> {
  const res = await fetch(`${BASE}/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: headers(userId),
  })
  return handleResponse<void>(res)
}

export async function askQuestion(
  sessionId: string,
  payload: AskPayload,
  userId?: string,
): Promise<AskResult> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/ask`, {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify(payload),
  })
  return handleResponse<AskResult>(res)
}

// ──────────────────────────────────────────────
// Contracts API
// ──────────────────────────────────────────────

export interface ContractSummary {
  id: string
  displayName: string
}

export async function listContracts(userId?: string): Promise<ContractSummary[]> {
  const res = await fetch(`${BASE}/contracts`, { headers: headers(userId) })
  return handleResponse<ContractSummary[]>(res)
}

// ──────────────────────────────────────────────
// Ingestion API
// ──────────────────────────────────────────────

export interface IngestJob {
  jobId: string
  contractId: string
  fileName: string
  status: 'queued' | 'processing' | 'done' | 'failed'
  stage: 'uploading' | 'parsing' | 'embedding' | 'indexing' | 'extracting' | 'graph_writing' | 'done' | 'error'
  progress: number
  error?: string | null
  result?: Record<string, unknown> | null
}

/** Upload one or more files. Returns one IngestJob per file (HTTP 202). */
export async function uploadFiles(
  files: File[],
  userId?: string,
): Promise<IngestJob[]> {
  const form = new FormData()
  for (const file of files) {
    form.append('files', file, file.name)
  }
  // Don't set Content-Type — browser sets it with the correct boundary
  const res = await fetch(`${BASE}/ingest`, {
    method: 'POST',
    headers: { 'X-User-Id': userId ?? DEFAULT_USER },
    body: form,
  })
  return handleResponse<IngestJob[]>(res)
}

/** Poll status for a single ingestion job. */
export async function getIngestStatus(
  jobId: string,
  userId?: string,
): Promise<IngestJob> {
  const res = await fetch(`${BASE}/ingest/${jobId}/status`, {
    headers: headers(userId),
  })
  return handleResponse<IngestJob>(res)
}

/** List all ingestion jobs for the current user. */
export async function listIngestJobs(userId?: string): Promise<IngestJob[]> {
  const res = await fetch(`${BASE}/ingest`, { headers: headers(userId) })
  return handleResponse<IngestJob[]>(res)
}
