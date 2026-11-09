import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { CourseworkHistoryView } from './CourseworkHistory'
import { StudyView } from './StudyView'
import { CourseCard } from './CourseCard'
import { SemesterPicker } from './SemesterPicker'
import { api, fileUrl, isTauriEnvironment } from './lib/api'
import type { Course, FilePreview, LibraryItem, ProcessingRecord } from './types'

const DocumentReader = lazy(() => import('./DocumentReader').then((module) => ({ default: module.DocumentReader })))

const categories = ['syllabi', 'readings', 'notes', 'generated', 'imports', 'other'] as const
type Category = 'all' | typeof categories[number]

const categoryLabels: Record<Category, string> = {
  all: 'All material',
  syllabi: 'Syllabi & guides',
  readings: 'Readings & references',
  notes: 'Notes & study aids',
  generated: 'AI-created material',
  imports: 'In intake folder',
  other: 'Other material',
}

const categoryDescriptions: Record<typeof categories[number], string> = {
  syllabi: 'Course context, syllabi, and assessment guides.',
  readings: 'Readings, references, and source material.',
  notes: 'Notes, lectures, reviews, and study aids.',
  generated: 'Secondary material created by an authorized AI agent.',
  imports: 'Files still in the course intake folder. Type is shown separately.',
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
  onOpenActions: (mode: 'import' | 'migration', courseId?: string) => void
  onHistoryChanged: () => Promise<void>
  studyResumeRequest: { courseId: string; sessionId: string } | null
  onStudyResumeConsumed: () => void
  onOpenStudyConversation: (conversationId: string) => void
  onStartStudyChat: (courseId: string, prompt?: string) => void
  courseOpenRequest: { id: string; courseId: string } | null
  onCourseOpenConsumed: () => void
  onBackHome: () => void
}

export function CoursesView({ semesters, semester, courses, items, inbox, loading, onSemesterChange, onOpenActions, onHistoryChanged, studyResumeRequest, onStudyResumeConsumed, onOpenStudyConversation, onStartStudyChat, courseOpenRequest, onCourseOpenConsumed, onBackHome }: CoursesViewProps) {
  const [selectedCourseId, setSelectedCourseId] = useState('')
  const [courseSection, setCourseSection] = useState<'material' | 'history' | 'study'>('material')
  const [category, setCategory] = useState<Category>('all')
  const [query, setQuery] = useState('')
  const [previewItem, setPreviewItem] = useState<LibraryItem | null>(null)
  const selectedCourse = courses.find((course) => course.id === selectedCourseId) ?? null
  const selectedItems = useMemo(() => selectedCourse ? items.filter((item) => item.course_id === selectedCourse.id) : [], [items, selectedCourse])
  const pendingPaths = useMemo(() => new Set(inbox.filter((item) => item.status !== 'ACKNOWLEDGED').map((item) => item.source_path)), [inbox])
  const counts = useMemo(() => {
    const result: Record<string, number> = {}
    for (const item of selectedItems) {
      const kind = item.category === 'imports' ? 'other' : item.category
      result[kind] = (result[kind] || 0) + 1
      if (item.intake_status === 'inbox' || item.category === 'imports') result.imports = (result.imports || 0) + 1
    }
    return result
  }, [selectedItems])
  const visibleItems = selectedItems.filter((item) => (
    (category === 'all' || (category === 'imports' ? item.intake_status === 'inbox' || item.category === 'imports' : item.category === category))
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

  useEffect(() => {
    if (!courseOpenRequest || !courses.some((course) => course.id === courseOpenRequest.courseId)) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedCourseId(courseOpenRequest.courseId)
    setCourseSection('material')
    setCategory('all')
    setQuery('')
    onCourseOpenConsumed()
  }, [courseOpenRequest, courses, onCourseOpenConsumed])

  useEffect(() => {
    if (!studyResumeRequest || !courses.some((course) => course.id === studyResumeRequest.courseId)) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelectedCourseId(studyResumeRequest.courseId)
    setCourseSection('study')
  }, [courses, studyResumeRequest])

  const chooseSemester = async (value: string) => {
    setSelectedCourseId('')
    setCategory('all')
    setQuery('')
    await onSemesterChange(value)
  }

  return <div className="page-stack">
    {!selectedCourse ? <>
      <PageIntro eyebrow="Academic library" title="Courses" subtitle="Choose a semester, open a class, and browse its material, coursework, and study history." />
      <div className="courses-toolbar">
        <SemesterPicker semester={semester} semesters={semesters} loading={loading} onSemesterChange={chooseSemester} />
        <span className="semester-status">{loading ? 'Loading semester…' : `${courses.length} class${courses.length === 1 ? '' : 'es'} · ${items.length} visible file${items.length === 1 ? '' : 's'}`}</span>
      </div>
      <section className="course-browser-grid">
        {courses.map((course) => <CourseCard key={course.id} course={course} onOpen={() => { setSelectedCourseId(course.id); setCategory('all'); setQuery('') }} />)}
        {!courses.length && <EmptyCourseState onOpenActions={() => onOpenActions('import')} />}
      </section>
    </> : <>
    <div className="course-detail-toolbar"><button className="course-back-button" onClick={onBackHome}><span aria-hidden="true">←</span> Home · all classes</button><SemesterPicker semester={semester} semesters={semesters} loading={loading} onSemesterChange={chooseSemester} /></div>
    <section className="course-material-panel course-own-page">
      <div className="course-material-heading"><div><p className="eyebrow">Class workspace</p><h3>{selectedCourse.name}</h3><p>{selectedCourse.path}</p></div><div className="course-material-heading-actions"><button className="secondary-button" onClick={() => onOpenActions('import', selectedCourse.id)}><span aria-hidden="true">+</span> Add material</button></div></div>
      <div className="course-section-tabs" role="tablist" aria-label={`${selectedCourse.name} sections`}><button type="button" role="tab" aria-selected={courseSection === 'material'} className={courseSection === 'material' ? 'active' : ''} onClick={() => setCourseSection('material')}>Course material</button><button type="button" role="tab" aria-selected={courseSection === 'history'} className={courseSection === 'history' ? 'active' : ''} onClick={() => setCourseSection('history')}>History</button><button type="button" role="tab" aria-selected={courseSection === 'study'} className={courseSection === 'study' ? 'active' : ''} onClick={() => setCourseSection('study')}>Study history</button><span className="course-material-count">{selectedItems.length} item{selectedItems.length === 1 ? '' : 's'}</span></div>
      {courseSection === 'study' ? <StudyView key={`${semester}:${selectedCourse.id}`} course={selectedCourse} semester={semester} materials={selectedItems} resumeSessionId={studyResumeRequest?.courseId === selectedCourse.id ? studyResumeRequest.sessionId : undefined} onResumeConsumed={onStudyResumeConsumed} onOpenConversation={onOpenStudyConversation} onStartStudyChat={onStartStudyChat} /> : courseSection === 'history' ? <CourseworkHistoryView course={selectedCourse} semester={semester} onHistoryChanged={onHistoryChanged} /> : <>
      <div className="material-category-grid">
        {categories.map((value) => <button type="button" className={`material-category-card ${category === value ? 'selected' : ''}`} data-category={value} key={value} onClick={() => setCategory(category === value ? 'all' : value)} aria-pressed={category === value}><span className="material-category-icon">{value === 'syllabi' ? '◈' : value === 'readings' ? '▤' : value === 'notes' ? '✎' : value === 'generated' ? '✦' : value === 'imports' ? '↓' : '•'}</span><strong>{categoryLabels[value]}</strong><span>{categoryDescriptions[value]}</span><b>{counts[value] || 0}</b></button>)}
      </div>
      <div className="course-material-toolbar"><label className="library-search"><span aria-hidden="true">⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${selectedCourse.code} material`} aria-label={`Search ${selectedCourse.name} material`} /></label><span>{visibleItems.length} shown</span></div>
      <div className="library-file-list">{visibleItems.map((item) => <LibraryFileRow item={item} pending={pendingPaths.has(item.path)} onOpen={() => setPreviewItem(item)} key={item.id} />)}{!visibleItems.length && <article className="course-material-empty"><strong>No files in this view</strong><p>{selectedItems.length ? 'Try another material category or search phrase.' : 'Import material into this class to populate its academic library.'}</p><button className="secondary-button" onClick={() => onOpenActions('import', selectedCourse.id)}>Import into this class <span>↓</span></button></article>}</div>
      </>}
    </section>
    </>}
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
  const assetUrl = preview && ['pdf', 'image'].includes(preview.kind) && !isTauriEnvironment() ? fileUrl(item.path, item.semester) : undefined
  return <div className="file-preview-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="file-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="file-preview-title"><header className="file-preview-heading"><div><p className="eyebrow">Read-only preview</p><h2 id="file-preview-title">{item.name}</h2><p>{item.relative_path}</p></div><button className="icon-button" aria-label="Close preview" onClick={onClose}>×</button></header>{loading && <div className="file-preview-loading" role="status">Opening a local preview…</div>}{error && <p className="setup-error" role="alert">{error}</p>}{preview && !loading && <><div className="file-preview-meta"><span>{preview.extension.toUpperCase().replace('.', '')} · {formatBytes(preview.size)}</span><span>Source unchanged</span></div><Suspense fallback={<div className="file-preview-loading" role="status">Formatting document…</div>}><DocumentReader preview={preview} assetUrl={assetUrl} emptyMessage="No extractable text was found. The original file remains available in this class." /></Suspense>{preview.truncated && <p className="file-preview-note">This preview is truncated for safety. The original file remains unchanged.</p>}{preview.kind === 'pdf' && isTauriEnvironment() && <p className="file-preview-note">The desktop shell shows extracted PDF text; page layout and scanned images are not included in this view.</p>}</>}</section></div>
}

function LibraryFileRow({ item, pending, onOpen }: { item: LibraryItem; pending: boolean; onOpen: () => void }) { const label = item.category === 'imports' ? 'Other material' : categoryLabels[item.category as Category]; const processingLabel = item.processing_status === 'PROCESSING' || item.processing_status === 'PENDING' || item.processing_status === 'DETECTED' ? 'Processing…' : item.processing_status === 'FAILED' ? 'Needs attention' : item.processing_status === 'ACKNOWLEDGED' ? item.extraction_status === 'unsupported_without_ocr' ? 'Processed · OCR needed' : 'Processed' : pending ? 'Awaiting processing' : null; const processingTone = item.processing_status === 'FAILED' ? 'tone-overdue' : item.processing_status === 'ACKNOWLEDGED' && item.extraction_status !== 'unsupported_without_ocr' ? 'tone-completed' : 'tone-soon'; const extension = item.extension.toLowerCase(); const fileTone = extension === '.pdf' ? 'file-pdf' : ['.ppt', '.pptx', '.key'].includes(extension) ? 'file-slides' : ['.doc', '.docx', '.md', '.txt'].includes(extension) ? 'file-text' : 'file-data'; return <button type="button" className="library-file-row" onClick={onOpen} aria-label={`Open ${item.name} preview`}><div className={`library-file-icon ${fileTone}`}>{item.extension.replace('.', '').slice(0, 4).toUpperCase() || 'FILE'}</div><div className="library-file-main"><strong>{item.name}</strong><span>{item.relative_path}</span><small>{label} · {item.semester}</small></div><div className="library-file-meta"><span>{formatBytes(item.size)}</span>{item.provenance === 'AI-GENERATED' && <em className="generated-badge">AI-generated{item.created_by ? ` · ${item.created_by}` : ''}</em>}{processingLabel && <em className={`file-status ${processingTone}`}>{processingLabel}</em>}{item.intake_status === 'inbox' && <em className="file-intake-status tone-soon">In intake folder</em>}<small>Open preview</small></div></button> }
function EmptyCourseState({ onOpenActions }: { onOpenActions: () => void }) { return <article className="course-selection-empty"><div className="empty-mark">◫</div><h3>No classes in this semester yet</h3><p>Import a syllabus or connect a workspace containing a recognized course structure. Academia OS will not invent a class from a filename.</p><button className="secondary-button" onClick={onOpenActions}>Import course material <span>↓</span></button></article> }
function PageIntro({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) { return <section className="page-intro"><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{subtitle}</p></section> }
function formatBytes(value: number): string { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`; return `${(value / (1024 * 1024)).toFixed(1)} MB` }
