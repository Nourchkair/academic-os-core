import type { Course } from './types'

export function CourseCard({ course, onOpen }: { course: Course; onOpen: () => void }) {
  const title = course.name.split(' - ').slice(1).join(' - ') || course.name
  const accents = ['blue', 'violet', 'teal'] as const
  const accent = accents[Array.from(course.code).reduce((sum, character) => sum + character.charCodeAt(0), 0) % accents.length]
  return <article className="course-browser-card-shell" data-accent={accent}>
    <button type="button" className="course-browser-card" onClick={onOpen} aria-label={`Open ${course.code}, ${title}`}>
      <div className="course-card-header"><span className="course-code">{course.code}</span></div>
      <h3>{title}</h3>
      <p>{course.material_count ? `${course.material_count} material item${course.material_count === 1 ? '' : 's'}` : 'No material indexed yet'}</p>
      <span className="course-browser-card-action">Open class <span>→</span></span>
    </button>
  </article>
}
