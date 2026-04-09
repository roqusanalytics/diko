import { useState, useRef, useEffect } from 'react'
import './Dropdown.css'

interface Option {
  value: string
  label: string
  description?: string
}

interface Props {
  value: string
  options: Option[]
  onChange: (value: string) => void
  placeholder?: string
}

export default function Dropdown({ value, options, onChange, placeholder = 'Pasirinkite...' }: Props) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  const selected = options.find(o => o.value === value)

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filtered = search.trim()
    ? options.filter(o =>
        o.label.toLowerCase().includes(search.toLowerCase()) ||
        o.value.toLowerCase().includes(search.toLowerCase()) ||
        (o.description || '').toLowerCase().includes(search.toLowerCase())
      )
    : options

  return (
    <div className="dropdown-wrap" ref={ref}>
      <div className="dropdown-trigger" onClick={() => { setOpen(!open); setSearch('') }}>
        <span className="dropdown-trigger-text">
          {selected ? selected.label : placeholder}
        </span>
        {selected?.description && (
          <span className="dropdown-trigger-desc">{selected.description}</span>
        )}
        <span className="dropdown-chevron">{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div className="dropdown-panel">
          {options.length > 5 && (
            <input
              className="dropdown-search"
              type="text"
              placeholder="Ieškoti..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              autoFocus
            />
          )}

          <div className="dropdown-options">
            {filtered.map(o => (
              <div
                key={o.value}
                className={`dropdown-option ${o.value === value ? 'selected' : ''}`}
                onClick={() => { onChange(o.value); setOpen(false); setSearch('') }}
              >
                <span className="dropdown-option-label">{o.label}</span>
                {o.description && <span className="dropdown-option-desc">{o.description}</span>}
                {o.value === value && <span className="dropdown-check">✓</span>}
              </div>
            ))}

            {filtered.length === 0 && (
              <div className="dropdown-empty">Nieko nerasta</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
