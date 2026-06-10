import type { ParagraphDetail, ParagraphSummary, SessionCreated, SessionStatus } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // non-JSON error body; keep the status text
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

const paragraphUrl = (sessionId: string, name: string) =>
  `/sessions/${sessionId}/paragraphs/${encodeURIComponent(name)}`

export const api = {
  createSession(file: File, targetLanguage: string): Promise<SessionCreated> {
    const form = new FormData()
    form.append('file', file)
    form.append('target_language', targetLanguage)
    return request('/sessions', { method: 'POST', body: form })
  },
  getStatus(sessionId: string): Promise<SessionStatus> {
    return request(`/sessions/${sessionId}`)
  },
  listParagraphs(sessionId: string): Promise<{ session_id: string; paragraphs: ParagraphSummary[] }> {
    return request(`/sessions/${sessionId}/paragraphs`)
  },
  getParagraph(sessionId: string, name: string): Promise<ParagraphDetail> {
    return request(paragraphUrl(sessionId, name))
  },
  translate(sessionId: string, name: string): Promise<unknown> {
    return request(`${paragraphUrl(sessionId, name)}/translate`, { method: 'POST' })
  },
  accept(sessionId: string, name: string): Promise<unknown> {
    return request(`${paragraphUrl(sessionId, name)}/accept`, { method: 'POST' })
  },
  reject(sessionId: string, name: string): Promise<unknown> {
    return request(`${paragraphUrl(sessionId, name)}/reject`, { method: 'POST' })
  },
  exportFileUrl(sessionId: string): string {
    return `/sessions/${sessionId}/export/file`
  },
}
