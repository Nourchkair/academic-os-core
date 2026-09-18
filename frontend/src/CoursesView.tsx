import { useEffect, useMemo, useState } from 'react'
import { api, fileUrl, isTauriEnvironment } from './lib/api'
import type { Course, FilePreview, LibraryItem, ProcessingRecord } from './types'

const categories = ['syllabi', 'readings', 'notes', 'imports', 'other'] as const
type Category = 'all' | typeof categories[number]

const categoryLabels: Record<Category, string> = {
  all: 'All material',
  syllabi: 'Syllabi & guides',
  readings: 'Readings & references',
  notes: 'Notes & study aids',
  imports: 'Imported material',
  other: 'Other material',
}

const categoryDescriptions: Record<typeof categories[number], string> = {
  syllabi: 'Course context, syllabi, and assessment guides.',
  readings: 'Readings, references, and source material.',
  notes: 'Notes, lectures, reviews, and study aids.',
  imports: 'Files waiting in the course intake folder.',
  other: 'Files that do not have a more specific category signal.',
}

type CoursesViewProps = {
  semesters: string[]
  semester: string
  courses: Course[]
  items: LibraryItem[]
  inbox: ProcessingRecord[]
  loading: boolean
  onSemesterChange: (semester: string) => Promise<void>
  onOpenActions: (mode: 'import' | 'migration') => void
}

export function CoursesView({ semesters, semester, courses, items, inbox, loading, onSemesterChange, onOpenActions }: CoursesViewProps) {
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [category, setCategory] = useState<Category>('all')
  const [query, setQuery] = useState('')
  const [previewItem, setPreviewItem] = useState<LibraryItem | null>(null)
  const selectedCourse = courses.find((course) => course.id === selectedCourseId) ?? null
  const selectedItems = useMemo(() => selectedCourse ? items.filter((item) => item.course_id === selectedCourse.id) : [], [items, selectedCourse])
  const pendingPaths = useMemo(() => new Set(inbox.filter((item) => item.status !== 'ACKNOWLEDGED').map((item) => item.source_path)), [inbox])
  const counts = useMemo(() => selectedItems.reduce<Record<string, number>>((result, item) => {
    result[item.category] = (result[item.category] || 0) + 1
    return result
  }, {}), [selectedItems])
  const visibleItems = selectedItems.filter((item) => (
    (category === 'all' || item.category === category)
    && (!query.trim() || `${item.name} ${item.relative_path}`.toLowerCase().includes(query.trim().toLowerCase()))
  ))

  useEffect(() => {
    if (selectedCourseId && !courses.some((course) => course.id === selectedCourseId)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedCourseId('')
      setCategory('all')
      setQuery('')
    }
  }, [courses, selectedCourseId])

  const chooseSemester = async (value: string) => {
    setSelectedCourseId('')
    setCategory('all')
    setQuery('')
    await onSemesterChange(value)
  }

  return <div className="page-stack">
    <PageIntro eyebrow="Academic library" title="Courses" subtitle="Choose a semester, open a class, and browse its syllabi, readings, notes, and imported material in one place. Files remain read-only until a separate approved action changes them." />
    <div className="courses-toolbar">
      <label className="semester-control"><span>Semester</span><select value={semester} onChange={(event) => void chooseSemester(event.target.value)} disabled={loading} aria-label="Choose semester">{semesters.map((value) => <option value={value} key={value}>{value}</option>)}</select></label>
      <span className="semester-status">{loading ? 'Loading semester…' : `${courses.length} class${courses.length === 1 ? '' : 'es'} · ${items.length} visible file${items.length === 1 ? '' : 's'}`}</span>
    </div>
    <section className="course-browser-grid">
      {courses.map((course) => <button type="button" className={`course-browser-card ${selectedCourse?.id === course.id ? 'selected' : ''}`} key={course.id} onClick={() => { setSelectedCourseId(course.id); setCategory('all'); setQuery('') }} aria-pressed={selectedCourse?.id === course.id}>
        <div className="course-card-header"><span className="course-code">{course.code}</span><span className={course.inbox_count ? 'review-dot' : 'complete-dot'}>{course.inbox_count ? 'Intake' : 'Ready'}</span></div>
        <h3>{course.name.split(' - ').slice(1).join(' - ') || course.name}</h3>
        <p>{course.material_count ? `${course.material_count} material item${course.material_count === 1 ? '' : 's'}` : 'No material indexed yet'}</p>
        <span className="course-browser-card-action">{selectedCourse?.id === course.id ? 'Opened' : 'Open class'} <span>→</span></span>
      </button>)}
      {!courses.length && <EmptyCourseState onOpenActions={() => onOpenActions('import')} />}
    </section>
    {selectedCourse ? <section className="course-material-panel">
      <div className="course-material-heading"><div><p className="eyebrow">Selected class</p><h3>{selectedCourse.name}</h3><p>{selectedCourse.path}</p></div><span className="course-material-count">{selectedItems.length} item{selectedItems.length === 1 ? '' : 's'}</span></div>
      <div className="material-category-grid">
        {categories.map((value) => <button type="button" className={`material-category-card ${category === value ? 'selected' : ''}`} key={value} onClick={() => setCategory(category === value ? 'all' : value)} aria-pressed={category === value}><span className="material-category-icon">{value === 'syllabi' ? '◈' : value === 'readings' ? '▤' : value === 'notes' ? '✎' : value === 'imports' ? '↓' : '•'}</span><strong>{categoryLabels[value]}</strong><span>{categoryDescriptions[value]}</span><b>{counts[value] || 0}</b></button>)}
      </div>
      <div className="course-material-toolbar"><label className="library-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${selectedCourse.code} material`} aria-label={`Search ${selectedCourse.name} material`} /></label><span>{visibleItems.length} shown</span></div>
      <div className="library-file-list">{visibleItems.map((item) => <LibraryFileRow item={item} pending={pendingPaths.has(item.path)} onOpen={() => setPreviewItem(item)} key={item.id} />)}{!visibleItems.length && <article className="course-material-empty"><strong>No files in this view</strong><p>{selectedItems.length ? 'Try another material category or search phrase.' : 'Import material into this class to populate its academic library.'}</p><button className="secondary-button" onClick={() => onOpenActions('import')}>Import into this class <span>↓</span></button></article>}</div>
    </section> : <section className="course-selection-empty"><div className="empty-mark">◫</div><h3>Choose a class to browse its material</h3><p>Each class opens its own Syllabi & guides, Readings & references, Notes & study aids, and Imported material sections.</p></section>}
    <FilePreviewDialog item={previewItem} onClose={() => setPreviewItem(null)} />
  </div>
}

function FilePreviewDialog({ item, onClose }: { item: LibraryItem | null; onClose: () => void }) {
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!item) return
    let active = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPreview(null)
    setError(null)
    setLoading(true)
    void api.filePreview(item.path, item.semester).then((value) => { if (active) setPreview(value) }).catch((reason) => { if (active) setError(String(reason)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [item])

  useEffect(() => {
    if (!item) return
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [item, onClose])

  if (!item) return null
  const pdfInBrowser = preview?.kind === 'pdf' && !isTauriEnvironment()
  return <div className="file-preview-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="file-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="file-preview-title"><header className="file-preview-heading"><div><p className="eyebrow">Read-only preview</p><h2 id="file-preview-title">{item.name}</h2><p>{item.relative_path}</p></div><button className="icon-button" aria-label="Close preview" onClick={onClose}>×</button></header>{loading && <div className="file-preview-loading" role="status">Opening a local preview…</div>}{error && <p className="setup-error" role="alert">{error}</p>}{preview && !loading && <><div className="file-preview-meta"><span>{preview.extension.toUpperCase().replace('.', '')} · {formatBytes(preview.size)}</span><span>Source unchanged</span></div>{pdfInBrowser ? <iframe className="pdf-preview-frame" src={fileUrl(item.path, item.semester)} title={`Preview of ${item.name}`} /> : <pre className="file-preview-content">{preview.content || 'No extractable text was found. The original file remains available in this class.'}</pre>}{preview.truncated && <p className="file-preview-note">This preview is truncated for safety. The original file remains unchanged.</p>}{preview.kind === 'pdf' && isTauriEnvironment() && <p className="file-preview-note">The desktop shell shows extracted PDF text here. Use the original file in Finder for full visual layout.</p>}</>}</section></div>
}

function LibraryFileRow({ item, pending, onOpen }: { item: LibraryItem; pending: boolean; onOpen: () => void }) { return <button type="button" className="library-file-row" onClick={onOpen} aria-label={`Open ${item.name} preview`}><div className="library-file-icon">{item.extension.replace('.', '').slice(0, 4).toUpperCase() || 'FILE'}</div><div className="library-file-main"><strong>{item.name}</strong><span>{item.relative_path}</span><small>{categoryLabels[item.category]} · {item.semester}</small></div><div className="library-file-meta"><span>{formatBytes(item.size)}</span>{pending && <em>Awaiting intake</em>}<small>Open preview</small></div></button> }
function EmptyCourseState({ onOpenActions }: { onOpenActions: () => void }) { return <article className="course-selection-empty"><div className="empty-mark">◫</div><h3>No classes in this semester yet</h3><p>Import a syllabus or connect a workspace containing a recognized course structure. Academia OS will not invent a class from a filename.</p><button className="secondary-button" onClick={onOpenActions}>Import course material <span>↓</span></button></article> }
function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function formatBytes(value: number): string { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`; return `${(value / (1024 * 1024)).toFixed(1)} MB` }
