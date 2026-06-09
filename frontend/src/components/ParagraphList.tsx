import type { ParagraphSummary } from '../types'

interface Props {
  paragraphs: ParagraphSummary[]
  selected: string | null
  onSelect: (name: string) => void
}

function confidenceLabel(score: number | null): string {
  return score === null ? '—' : `${Math.round(score * 100)}%`
}

export function ParagraphList({ paragraphs, selected, onSelect }: Props) {
  return (
    <ul className="paragraph-list">
      {paragraphs.map((paragraph) => (
        <li key={paragraph.name}>
          <button
            className={paragraph.name === selected ? 'selected' : ''}
            onClick={() => onSelect(paragraph.name)}
          >
            <span className="name">{paragraph.name}</span>
            <span className={`status status-${paragraph.status.toLowerCase()}`}>{paragraph.status}</span>
            <span className="confidence">{confidenceLabel(paragraph.confidence_score)}</span>
            {paragraph.risk_flags.includes('MANDATORY_REVIEW') && (
              <span className="flag mandatory" title="Mandatory review">⚑</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  )
}
