import { useState } from 'react'

interface Props {
  busy: boolean
  onCreate: (file: File, targetLanguage: string) => void
}

export function UploadForm({ busy, onCreate }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [targetLanguage, setTargetLanguage] = useState('python')

  return (
    <form
      className="upload"
      onSubmit={(event) => {
        event.preventDefault()
        if (file) onCreate(file, targetLanguage)
      }}
    >
      <label>
        COBOL source
        <input
          type="file"
          accept=".cbl,.cob"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      <label>
        Target language
        <select value={targetLanguage} onChange={(event) => setTargetLanguage(event.target.value)}>
          <option value="python">Python</option>
          <option value="java">Java</option>
        </select>
      </label>
      <button type="submit" disabled={busy || !file}>
        {busy ? 'Working…' : 'Start review'}
      </button>
    </form>
  )
}
