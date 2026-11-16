import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SemesterPicker } from './SemesterPicker'

describe('SemesterPicker', () => {
  it('opens, navigates with the keyboard, and selects a semester', async () => {
    const onSemesterChange = vi.fn().mockResolvedValue(undefined)
    render(
      <SemesterPicker
        semester="Fall 2026"
        semesters={['Winter 2026', 'Fall 2026', 'Winter 2027']}
        loading={false}
        onSemesterChange={onSemesterChange}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Choose semester' })
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('listbox', { name: 'Available semesters' })).toBeInTheDocument()

    const selected = screen.getByRole('option', { name: /Fall 2026/ })
    expect(selected).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(selected, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(screen.getByRole('option', { name: /Winter 2027/ }))

    fireEvent.click(screen.getByRole('option', { name: /Winter 2027/ }))
    expect(onSemesterChange).toHaveBeenCalledWith('Winter 2027')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes on Escape and returns focus to the trigger', () => {
    render(
      <SemesterPicker
        semester="Fall 2026"
        semesters={['Fall 2026']}
        loading={false}
        onSemesterChange={vi.fn().mockResolvedValue(undefined)}
      />,
    )

    const trigger = screen.getByRole('button', { name: 'Choose semester' })
    fireEvent.click(trigger)
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(document.activeElement).toBe(trigger)
  })

  it('does not open while loading or without semesters', () => {
    const { rerender } = render(
      <SemesterPicker semester="" semesters={['Fall 2026']} loading onSemesterChange={vi.fn().mockResolvedValue(undefined)} />,
    )
    expect(screen.getByRole('button', { name: 'Choose semester' })).toBeDisabled()

    rerender(<SemesterPicker semester="" semesters={[]} loading={false} onSemesterChange={vi.fn().mockResolvedValue(undefined)} />)
    expect(screen.getByRole('button', { name: 'Choose semester' })).toBeDisabled()
  })
})
