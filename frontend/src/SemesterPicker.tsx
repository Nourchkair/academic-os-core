import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

type SemesterPickerProps = {
  semester: string
  semesters: string[]
  loading: boolean
  onSemesterChange: (semester: string) => Promise<void>
}

export function SemesterPicker({ semester, semesters, loading, onSemesterChange }: SemesterPickerProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    const dismissOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const dismissEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', dismissOutside)
    document.addEventListener('keydown', dismissEscape)
    menuRef.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus()
    return () => {
      document.removeEventListener('pointerdown', dismissOutside)
      document.removeEventListener('keydown', dismissEscape)
    }
  }, [open])

  const selectSemester = (value: string) => {
    setOpen(false)
    triggerRef.current?.focus()
    if (value !== semester) void onSemesterChange(value)
  }

  const moveFocus = (event: ReactKeyboardEvent<HTMLButtonElement>, direction: -1 | 1) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const options = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [])
    const current = options.indexOf(event.currentTarget)
    const next = options[(current + direction + options.length) % options.length]
    next?.focus()
  }

  return <div className="semester-control">
    <span>Semester</span>
    <div className="semester-picker" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="semester-picker-trigger"
        aria-label="Choose semester"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={loading || semesters.length === 0}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !open) {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        <span className="semester-picker-value">{semester || 'Choose semester'}</span>
        <svg className={`semester-picker-chevron ${open ? 'open' : ''}`} viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
      </button>
      {open && <div className="semester-picker-menu" id={menuId} role="listbox" aria-label="Available semesters" ref={menuRef}>
        <div className="semester-picker-heading">Choose a semester</div>
        {semesters.map((value) => <button
          type="button"
          role="option"
          aria-selected={value === semester}
          className="semester-picker-option"
          key={value}
          onClick={() => selectSemester(value)}
          onKeyDown={(event) => moveFocus(event, event.key === 'ArrowDown' ? 1 : -1)}
        >
          <span className="semester-option-mark" aria-hidden="true">{value === semester ? '✓' : ''}</span>
          <span>{value}</span>
          {value === semester && <small>Selected</small>}
        </button>)}
      </div>}
    </div>
  </div>
}
