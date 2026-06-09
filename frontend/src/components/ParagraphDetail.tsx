import type { ParagraphDetail as Detail } from '../types'

interface Props {
  detail: Detail
  busy: boolean
  onTranslate: () => void
  onAccept: () => void
  onReject: () => void
}

export function ParagraphDetail({ detail, busy, onTranslate, onAccept, onReject }: Props) {
  const translated = detail.translated_text
  return (
    <section className="detail">
      <header>
        <h2>{detail.name}</h2>
        <span className={`status status-${detail.status.toLowerCase()}`}>{detail.status}</span>
        {detail.confidence_score !== null && (
          <span className="confidence">confidence {Math.round(detail.confidence_score * 100)}%</span>
        )}
      </header>

      {detail.risk_flags.length > 0 && (
        <ul className="risk-flags">
          {detail.risk_flags.map((flag) => (
            <li key={flag} className={flag === 'MANDATORY_REVIEW' ? 'mandatory' : ''}>
              {flag}
            </li>
          ))}
        </ul>
      )}

      <div className="panes">
        <div className="pane">
          <h3>Original COBOL</h3>
          <pre>{detail.source || '(empty)'}</pre>
        </div>
        <div className="pane">
          <h3>Suggested translation</h3>
          <pre>{translated ?? 'Not translated yet.'}</pre>
        </div>
      </div>

      <div className="actions">
        <button onClick={onTranslate} disabled={busy}>
          {translated ? 'Re-translate' : 'Translate'}
        </button>
        <button onClick={onAccept} disabled={busy || !translated} title={!translated ? 'Translate first' : ''}>
          Accept
        </button>
        <button onClick={onReject} disabled={busy}>
          Reject
        </button>
      </div>
    </section>
  )
}
