import { useCallback, useState } from 'react'

import { api } from './api'
import { ParagraphDetail } from './components/ParagraphDetail'
import { ParagraphList } from './components/ParagraphList'
import { UploadForm } from './components/UploadForm'
import type { ParagraphDetail as Detail, ParagraphSummary, SessionStatus } from './types'

export default function App() {
  const [session, setSession] = useState<SessionStatus | null>(null)
  const [paragraphs, setParagraphs] = useState<ParagraphSummary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }, [])

  const refresh = useCallback(async (sessionId: string) => {
    const [status, list] = await Promise.all([api.getStatus(sessionId), api.listParagraphs(sessionId)])
    setSession(status)
    setParagraphs(list.paragraphs)
  }, [])

  const onCreate = (file: File, targetLanguage: string) =>
    run(async () => {
      const created = await api.createSession(file, targetLanguage)
      setSelected(null)
      setDetail(null)
      await refresh(created.id)
    })

  const onSelect = (name: string) =>
    run(async () => {
      if (!session) return
      setSelected(name)
      setDetail(await api.getParagraph(session.id, name))
    })

  const afterParagraphAction = async (sessionId: string, name: string) => {
    setDetail(await api.getParagraph(sessionId, name))
    await refresh(sessionId)
  }

  const onTranslate = () =>
    run(async () => {
      if (!session || !selected) return
      await api.translate(session.id, selected)
      await afterParagraphAction(session.id, selected)
    })

  const onAccept = () =>
    run(async () => {
      if (!session || !selected) return
      await api.accept(session.id, selected)
      await afterParagraphAction(session.id, selected)
    })

  const onReject = () =>
    run(async () => {
      if (!session || !selected) return
      await api.reject(session.id, selected)
      await afterParagraphAction(session.id, selected)
    })

  return (
    <div className="app">
      <header className="app-header">
        <h1>Punchcard</h1>
        <p>LLM-assisted COBOL review with human-in-the-loop accept / reject.</p>
      </header>

      <UploadForm busy={busy} onCreate={onCreate} />

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {session && (
        <>
          <div className="session-bar">
            <span>
              <strong>{session.program_id ?? session.filename}</strong> → {session.target_language}
            </span>
            <span>{Math.round(session.progress * 100)}% reviewed</span>
            <span>
              {session.accepted_count} accepted · {session.rejected_count} rejected · {session.paragraph_count} total
            </span>
            <a className="export" href={api.exportFileUrl(session.id)}>
              Download translation
            </a>
          </div>

          <div className="workbench">
            <ParagraphList paragraphs={paragraphs} selected={selected} onSelect={onSelect} />
            {detail ? (
              <ParagraphDetail
                detail={detail}
                busy={busy}
                onTranslate={onTranslate}
                onAccept={onAccept}
                onReject={onReject}
              />
            ) : (
              <p className="hint">Select a paragraph to review its translation.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
