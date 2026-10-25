'use client'
import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

export function Explanation({ text }: { text: string | null }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  const [plain, tech] = text.split(' Evidence: ')
  return (
    <div className="explanation">
      <p>{plain}</p>
      {tech && (
        <button className="disclosure" onClick={() => setOpen(!open)}>
          {open ? <ChevronDown /> : <ChevronRight />} Technical evidence
        </button>
      )}
      {open && (
        <>
          <code>{tech}</code>
          <p className="muted-text">Amounts inside the technical evidence are in dataset dollars (USD), shown unconverted.</p>
        </>
      )}
    </div>
  )
}
