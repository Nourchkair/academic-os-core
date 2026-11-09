import { lazy, Suspense, useEffect, useState } from 'react'
import { api, fileUrl, isTauriEnvironment } from './lib/api'
import type { Course, CourseworkHistoryRecord, CourseworkHistoryInput } from './types'
import type { FilePreview } from './types'

const DocumentReader = lazy(() => import('./DocumentReader').then((module) => ({ default: module.DocumentReader })))

const kindOptions = [
  ['assignment', 'Assignment'], ['essay', 'Essay'], ['project', 'Project'], ['exam', 'Exam'],
  ['presentation', 'Presentation'], ['quiz', 'Quiz'], ['other', 'Other'],
] as const
const statusOptions = [
  ['planned', 'Planned'], ['in_progress', 'In progress'], ['submitted', 'Submitted'],
  ['graded', 'Graded'], ['completed', 'Completed'],
] as const

export function CourseworkHistoryView({ course, semester, onHistoryChanged }: { course: Course; semester: string; onHistoryChanged: () => Promise<void> }) {
  const [records, setRecords] = useState<CourseworkHistoryRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [previewPath, setPreviewPath] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    setError(null)
    void api.courseworkHistory(course.id, semester)
      .then((value) => { if (active) setRecords(value) })
      .catch((reason) => { if (active) setError(String(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [course.id, semester])

  const saveNew = async (input: CourseworkHistoryInput) => {
    const record = await api.addCourseworkHistory(course.id, semester, input)
    setRecords((current) => [...current, record])
    setAdding(false)
    setError(null)
    await onHistoryChanged()
  }

  const saveUpdate = async (recordId: string, input: CourseworkHistoryInput) => {
    const record = await api.updateCourseworkHistory(course.id, semester, recordId, input)
    setRecords((current) => current.map((item) => item.id === recordId ? record : item))
    setEditingId(null)
    setError(null)
    await onHistoryChanged()
  }

  const orderedRecords = [...records].sort((a, b) => (b.submitted_on || b.due_date || b.created_at).localeCompare(a.submitted_on || a.due_date || a.created_at))

  return <section className="coursework-history">
    <div className="coursework-history-heading"><div><p className="eyebrow">Coursework archive</p><h3>Assignments & projects</h3><p>Keep a record of what you worked on, its status, and the files associated with it. Records are stored in this course folder.</p></div><button className="primary-button" type="button" onClick={() => { setAdding((value) => !value); setEditingId(null) }}>{adding ? 'Close form' : 'Add history item'} <span>{adding ? '×' : '+'}</span></button></div>
    {error && <p className="setup-error" role="alert">{error}</p>}
    {adding && <CourseworkEditor onSave={saveNew} onCancel={() => setAdding(false)} />}
    {loading ? <p className="muted-copy" role="status">Loading {course.code} history…</p> : orderedRecords.length ? <div className="coursework-history-list">{orderedRecords.map((record) => <article className="coursework-history-card" key={record.id}>
      {editingId === record.id ? <CourseworkEditor key={record.id} initial={record} onSave={(input) => saveUpdate(record.id, input)} onCancel={() => setEditingId(null)} /> : <>
        <div className="coursework-history-card-heading"><div><span className="history-kind">{labelForKind(record.kind)}</span><h4>{record.title}</h4></div><span className={`history-status status-${record.status}`}>{labelForStatus(record.status)}</span></div>
        <div className="coursework-history-meta">{record.due_date && <span>Due {formatDate(record.due_date)}</span>}{record.submitted_on && <span>Submitted {formatDate(record.submitted_on)}</span>}{record.grade && <span>Grade {record.grade}</span>}</div>
        {record.notes && <p className="coursework-history-notes">{record.notes}</p>}
        {!!record.artifact_paths.length && <div className="history-artifacts"><strong>Files</strong>{record.artifact_paths.map((path) => <button type="button" className="history-artifact-link" key={path} onClick={() => setPreviewPath(path)}>{path.split('/').pop()} <span>Preview</span></button>)}</div>}
        {!!record.status_history.length && <details className="history-status-log"><summary>Status log</summary><ol>{record.status_history.map((event, index) => <li key={`${event.recorded_at}-${index}`}><strong>{labelForStatus(event.status)}</strong> · {formatDateTime(event.recorded_at)} · {event.basis}</li>)}</ol></details>}
        <button type="button" className="history-edit-button" onClick={() => { setEditingId(record.id); setAdding(false) }}>Edit record</button>
      </>}
    </article>)}</div> : !adding && <article className="course-material-empty"><strong>No coursework history yet</strong><p>Add an assignment, essay, project, or exam to keep its status and related files with this class.</p><button type="button" className="secondary-button" onClick={() => setAdding(true)}>Add the first item <span>+</span></button></article>}
    {previewPath && <HistoryFilePreview course={course} semester={semester} relativePath={previewPath} onClose={() => setPreviewPath(null)} />}
  </section>
}

function CourseworkEditor({ initial, onSave, onCancel }: { initial?: CourseworkHistoryRecord; onSave: (input: CourseworkHistoryInput) => Promise<void>; onCancel: () => void }) {
  const [kind, setKind] = useState<CourseworkHistoryInput['kind']>(initial?.kind ?? 'assignment')
  const [title, setTitle] = useState(initial?.title ?? '')
  const [status, setStatus] = useState<CourseworkHistoryInput['status']>(initial?.status ?? 'in_progress')
  const [taskTitle, setTaskTitle] = useState(initial?.task_title ?? '')
  const [dueDate, setDueDate] = useState(initial?.due_date ?? '')
  const [submittedOn, setSubmittedOn] = useState(initial?.submitted_on ?? '')
  const [grade, setGrade] = useState(initial?.grade ?? '')
  const [artifactPaths, setArtifactPaths] = useState((initial?.artifact_paths ?? []).join('\n'))
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave({
        kind, title, status, task_title: taskTitle, due_date: dueDate, submitted_on: submittedOn,
        grade, artifact_paths: artifactPaths.split('\n').map((path) => path.trim()).filter(Boolean), notes,
      })
    } catch (reason) {
      setError(String(reason))
    } finally {
      setSaving(false)
    }
  }

  return <form className="coursework-editor" onSubmit={(event) => void submit(event)}>
    <div className="coursework-editor-grid">
      <label><span>Type</span><select value={kind} onChange={(event) => setKind(event.target.value as CourseworkHistoryInput['kind'])}>{kindOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value as CourseworkHistoryInput['status'])}>{statusOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className="history-title-field"><span>Title</span><input value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} required placeholder="e.g. First Essay — Question 3" /></label>
      <label><span>Related task title <small>(optional)</small></span><input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} maxLength={200} placeholder="Match a task or deadline" /></label>
      <label><span>Due date</span><input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label>
      <label><span>Submitted on</span><input type="date" value={submittedOn} onChange={(event) => setSubmittedOn(event.target.value)} /></label>
      <label><span>Grade <small>(optional)</small></span><input value={grade} onChange={(event) => setGrade(event.target.value)} maxLength={50} placeholder="Not graded yet" /></label>
      <label className="history-wide-field"><span>Course-relative file paths <small>(one per line)</small></span><textarea value={artifactPaths} onChange={(event) => setArtifactPaths(event.target.value)} rows={2} placeholder="03_ASSIGNMENTS/A01 - First Essay/Submission/final.docx" /></label>
      <label className="history-wide-field"><span>Notes <small>(optional)</small></span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} maxLength={900} placeholder="Add useful context about this coursework record." /></label>
    </div>
    {error && <p className="setup-error" role="alert">{error}</p>}
    <p className="history-form-note">This records coursework in your local workspace; it does not submit work to your school.</p>
    <div className="coursework-editor-actions"><button type="button" className="secondary-button" onClick={onCancel} disabled={saving}>Cancel</button><button type="submit" className="primary-button" disabled={saving || !title.trim()}>{saving ? 'Saving…' : initial ? 'Save changes' : 'Add to history'}</button></div>
  </form>
}

function HistoryFilePreview({ course, semester, relativePath, onClose }: { course: Course; semester: string; relativePath: string; onClose: () => void }) {
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const path = `${course.path}/${relativePath}`
  useEffect(() => {
    let active = true
    void api.filePreview(path, semester).then((value) => { if (active) setPreview(value) }).catch((reason) => { if (active) setError(String(reason)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [path, semester])
  const assetUrl = preview && ['pdf', 'image'].includes(preview.kind) && !isTauriEnvironment() ? fileUrl(path, semester) : undefined
  return <div className="file-preview-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="file-preview-dialog" role="dialog" aria-modal="true" aria-label={`Preview ${relativePath.split('/').pop()}`}><header className="file-preview-heading"><div><p className="eyebrow">Coursework file</p><h2>{relativePath.split('/').pop()}</h2><p>{relativePath}</p></div><button className="icon-button" aria-label="Close preview" onClick={onClose}>×</button></header>{loading && <div className="file-preview-loading" role="status">Opening a local preview…</div>}{error && <p className="setup-error" role="alert">{error}</p>}{preview && !loading && <><div className="file-preview-meta"><span>{preview.extension.toUpperCase().replace('.', '')} · {formatBytes(preview.size)}</span>{assetUrl ? <a href={assetUrl} target="_blank" rel="noreferrer">Open original</a> : <span>Source unchanged</span>}</div><Suspense fallback={<div className="file-preview-loading" role="status">Formatting document…</div>}><DocumentReader preview={preview} assetUrl={assetUrl} emptyMessage="No extractable text was found. Open the original file to view its full contents." /></Suspense></>}</section></div>
}

function labelForKind(kind: string) { return kindOptions.find(([value]) => value === kind)?.[1] ?? kind }
function labelForStatus(status: string) { return statusOptions.find(([value]) => value === status)?.[1] ?? status }
function formatDate(value: string) { const date = new Date(`${value.slice(0, 10)}T12:00:00`); return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) }
function formatDateTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) }
function formatBytes(value: number) { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`; return `${(value / (1024 * 1024)).toFixed(1)} MB` }
