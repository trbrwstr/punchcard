export interface SessionCreated {
  id: string
  filename: string
  program_id: string | null
  target_language: string
  status: string
  progress: number
  paragraph_count: number
}

export interface SessionStatus extends SessionCreated {
  translated_count: number
  accepted_count: number
  rejected_count: number
  created_at: string
  updated_at: string
}

export interface ParagraphSummary {
  name: string
  status: string
  confidence_score: number | null
  risk_flags: string[]
}

export interface ParagraphDetail extends ParagraphSummary {
  source: string
  translated_text: string | null
}
