import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { CourseCard } from './CourseCard'
import type { Course } from './types'

const course: Course = {
  id: 'POL 2103 - Politics',
  code: 'POL 2103',
  name: 'POL 2103 - Politics',
  path: '/workspace/Fall 2026/POL 2103 - Politics',
  inbox_count: 0,
  material_count: 3,
  review_required: false,
}

describe('CourseCard', () => {
  it('renders the course identity and opens the course', () => {
    const onOpen = vi.fn()
    render(<CourseCard course={course} onOpen={onOpen} />)

    expect(screen.getByText('POL 2103')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Politics' })).toBeInTheDocument()
    expect(screen.getByText('3 material items')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open POL 2103, Politics' }))
    expect(onOpen).toHaveBeenCalledTimes(1)
  })

  it('reports an empty material inventory honestly', () => {
    render(<CourseCard course={{ ...course, material_count: 0 }} onOpen={() => undefined} />)
    expect(screen.getByText('No material indexed yet')).toBeInTheDocument()
  })
})
