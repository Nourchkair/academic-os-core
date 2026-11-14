import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import { api, isTauriEnvironment } from './lib/api'
import type { Course, ExtractionPreview, ImportResult, StatusPayload } from './types'

type ImportViewProps = {
  status: StatusPayload
  courses: Course[]
  semester?: string
  initialCourseId?: string
  initialFiles?: File[]
  onImported: () => Promise<void>
}

export function ImportView({ status, courses, semester, initialCourseId, initialFiles, onImported }: ImportViewProps) {
  const [paths, setPaths] = useState<string[]>([])
  const [browserFiles, setBrowserFiles] = useState<File[]>([])
  const [destination, setDestination] = useState(() => courses.some((course) => course.id === initialCourseId) ? initialCourseId as string : 'general')
  const [uncertain, setUncertain] = useState(() => !courses.some((course) => course.id === initialCourseId))
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<ImportResult[]>([])
  const [syllabusPreview, setSyllabusPreview] = useState<ExtractionPreview | null>(null)
  const [verifiedCurrent, setVerifiedCurrent] = useState(false)
  const [preflight, setPreflight] = useState<Array<{ key: string; name: string; size?: number; extractable?: boolean; ocr?: boolean; duplicate?: { identical: boolean; name: string } | null; missing?: string }>>([])
  const [skipped, setSkipped] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const tauriEnvironment = isTauriEnvironment()
  const receivedInitialFiles = useRef(false)
  useEffect(() => {
    if (receivedInitialFiles.current || !initialFiles?.length) return
    receivedInitialFiles.current = true
    addBrowserFiles(initialFiles)
  }, [initialFiles])

  const addBrowserFiles = (selected: File[]) => {
    if (!selected.length) {
      setError('No files were found in that selection.')
      return
    }
    setBrowserFiles((current) => {
      const known = new Set(current.map(fileKey))
      return [...current, ...selected.filter((file) => {
        const key = fileKey(file)
        if (known.has(key)) return false
        known.add(key)
        return true
      })]
    })
    setSyllabusPreview(null)
    setError(null)
  }

  const clearSelected = () => {
    setPaths([])
    setBrowserFiles([])
    setSyllabusPreview(null)
    setVerifiedCurrent(false)
    setSkipped([])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  useEffect(() => {
    if (!tauriEnvironment) return
    let unlisten: (() => void) | undefined
    void getCurrentWebview().onDragDropEvent((event) => {
      const payload = event.payload
      if (payload.type === 'enter') setDragging(true)
      if (payload.type === 'leave') setDragging(false)
      if (payload.type === 'drop' && 'paths' in payload) {
        setDragging(false)
        setPaths((current) => Array.from(new Set([...current, ...payload.paths])))
        setSyllabusPreview(null)
      }
    }).then((stop) => { unlisten = stop })
    return () => unlisten?.()
  }, [tauriEnvironment])

  const selectedCourse = courses.find((course) => course.id === destination)
  const targetSemester = semester || status.workspace.semester
  const destinationPath = selectedCourse ? `${selectedCourse.path}/00_INBOX` : `${status.workspace.academic_root}/${targetSemester}/00_INBOX`
  const requiresReview = uncertain || !selectedCourse
  useEffect(() => {
    let active = true
    if (!paths.length) {
      if (!browserFiles.length) setPreflight([])
      return () => { active = false }
    }
    const request = isTauriEnvironment() ? api.importPreflightDesktop(paths, destinationPath) : api.importPreflight(paths, destinationPath)
    void request.then((value) => {
      if (!active) return
      setPreflight(value.files.map((file) => ({
        key: file.path,
        name: file.name,
        size: file.size,
        extractable: file.extractable,
        ocr: file.ocr_may_be_needed,
        duplicate: file.duplicate ? { identical: file.duplicate.identical, name: file.duplicate.name } : null,
        missing: file.status === 'missing' ? file.reason : undefined,
      })))
    }).catch(() => {
      if (active) setPreflight(paths.map((path) => ({ key: path, name: basename(path) })))
    })
    return () => { active = false }
  }, [paths, destinationPath])
  useEffect(() => {
    if (paths.length) return
    setPreflight(browserFiles.map((file) => ({
      key: fileKey(file),
      name: file.name,
      size: file.size,
      extractable: /\.(pdf|docx|pptx|txt|text|md|markdown|csv|json|yaml|yml)$/i.test(file.name),
      ocr: /\.pdf$/i.test(file.name),
      duplicate: null,
    })))
  }, [browserFiles, paths.length])
  const suggestions = useMemo(() => paths.map((path) => ({ path, course: suggestCourse(path, courses) })), [paths, courses])
  const selectedCount = paths.length + browserFiles.length
  // Browser File objects do not expose a safe local path. Only native Tauri paths
  // may be sent to the syllabus extraction command.
  const syllabusPath = tauriEnvironment && paths.length === 1 && isSyllabusPath(paths[0]) ? paths[0] : null
  const canPreviewSyllabus = Boolean(syllabusPath && selectedCourse)

  const chooseFiles = async () => {
    if (!tauriEnvironment) {
      fileInputRef.current?.click()
      return
    }
    try {
      const chosen = await open({ multiple: true, directory: false, title: 'Choose academic material' })
      if (!chosen) return
      const selected = Array.isArray(chosen) ? chosen : [chosen]
      setPaths((current) => Array.from(new Set([...current, ...selected])))
      setSyllabusPreview(null)
      setError(null)
    } catch (reason) {
      setError(`The file picker could not open: ${String(reason)}`)
    }
  }

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (tauriEnvironment) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (tauriEnvironment) return
    event.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    if (tauriEnvironment) return
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false)
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    if (tauriEnvironment) return
    event.preventDefault()
    setDragging(false)
    addBrowserFiles(Array.from(event.dataTransfer.files))
  }

  const handleBrowserFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    addBrowserFiles(Array.from(event.currentTarget.files ?? []))
    // Allow the same file to be selected again after clearing or importing.
    event.currentTarget.value = ''
  }

  const previewSyllabus = async () => {
    if (!syllabusPath || !selectedCourse) {
      setError('Choose one syllabus file and a recognized course before previewing it.')
      return
    }
    try {
      setBusy(true)
      setError(null)
      setSyllabusPreview(await api.extractSyllabus(syllabusPath, selectedCourse.id, verifiedCurrent, false))
    } catch (reason) {
      setError(`The syllabus preview could not be completed: ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const applySyllabus = async () => {
    if (!syllabusPath || !selectedCourse) return
    try {
      setBusy(true)
      setError(null)
      setSyllabusPreview(await api.extractSyllabus(syllabusPath, selectedCourse.id, verifiedCurrent, true))
      await onImported()
    } catch (reason) {
      setError(`Nothing was changed. Supported syllabus information could not be added: ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const importSelected = async () => {
    if (!selectedCount) {
      setError('Choose or drop at least one file first.')
      return
    }
    try {
      setBusy(true)
      setError(null)
      const imported: ImportResult[] = []
      if (tauriEnvironment) {
        for (const path of paths.filter((path) => !skipped.includes(path))) imported.push(await api.importFile(path, destinationPath, requiresReview))
      } else {
        for (const file of browserFiles.filter((file) => !skipped.includes(fileKey(file)))) imported.push(await api.uploadFile(file, destinationPath, requiresReview))
      }
      setResults(imported)
      clearSelected()
      await onImported()
    } catch (reason) {
      setError(`Nothing was moved. The import could not be completed: ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  const includedCount = selectedCount - skipped.length
  return <div className="page-stack">
    <section className="page-intro"><p className="eyebrow">Safe intake</p><h2>Import material</h2><p>Bring in school files without moving the originals. Choose a course when you know it; otherwise send the copy to general intake for an authorized external agent to process later.</p></section>
    <section className={`drop-zone ${dragging ? 'dragging' : ''}`} onDragOver={tauriEnvironment ? undefined : handleDragOver} onDragEnter={tauriEnvironment ? undefined : handleDragEnter} onDragLeave={tauriEnvironment ? undefined : handleDragLeave} onDrop={tauriEnvironment ? undefined : handleDrop}><div className="drop-icon">↓</div><h3>Drop files here</h3><p>PDFs, documents, slides, notes, or other local academic material.</p><button className="primary-button" onClick={() => void chooseFiles()}>Choose files</button>{!tauriEnvironment && <input ref={fileInputRef} className="browser-file-input" type="file" multiple onChange={handleBrowserFileChange} aria-label="Choose academic material from this computer" />}{!tauriEnvironment ? <small>Files remain on this computer and are passed to the local dashboard only.</small> : <small>Files are copied into the workspace. The original stays where it is.</small>}</section>
    {selectedCount > 0 && <section className="import-panel">
      <div className="section-heading"><div><p className="eyebrow">Selected material</p><h3>{selectedCount} file{selectedCount === 1 ? '' : 's'} ready</h3></div><button className="quiet-button" onClick={clearSelected}>Clear</button></div>
      <div className="selected-files">
        {preflight.map((row) => {
          const included = !skipped.includes(row.key)
          const facts = [
            row.size ? formatBytes(row.size) : null,
            row.missing ? null : row.extractable === false ? 'kept as-is, no text extraction' : 'text searchable',
            row.ocr ? 'OCR may be needed' : null,
          ].filter(Boolean).join(' · ')
          return <article className={`selected-file ${included ? '' : 'excluded'} ${row.missing ? 'missing' : ''}`} key={row.key}>
            <label className="check-row selected-file-check"><input type="checkbox" checked={included} aria-label={`Include ${row.name}`} onChange={() => setSkipped((current) => included ? [...current, row.key] : current.filter((key) => key !== row.key))} /></label>
            <div>
              <strong>{row.name}</strong>
              <small>{row.missing || facts}</small>
              {row.duplicate && <small className="import-duplicate">{row.duplicate.identical ? 'Identical copy already in this inbox — uncheck to skip it.' : `Same filename already in this inbox: ${row.duplicate.name}`}</small>}
            </div>
          </article>
        })}
        {!preflight.length && <p className="account-note">Inspecting the selection…</p>}
      </div>
      <div className="import-options"><label className="setup-field"><span>Destination</span><select value={destination} onChange={(event) => { setDestination(event.target.value); setUncertain(event.target.value === 'general'); setSyllabusPreview(null) }}><option value="general">General intake — I’m not sure where this belongs</option>{courses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name.split(' - ').slice(1).join(' - ') || course.name}</option>)}</select></label><label className="check-row"><input type="checkbox" checked={uncertain} onChange={(event) => setUncertain(event.target.checked)} /><span>Keep classification uncertain for an authorized external agent</span></label></div>
      {canPreviewSyllabus && <section className="extraction-preview"><p className="eyebrow">Controlled extraction</p><h3>Syllabus preview</h3>{!syllabusPreview ? <><p>Analyze this syllabus locally before adding anything. The original file will not be changed.</p><label className="check-row"><input type="checkbox" checked={verifiedCurrent} onChange={(event) => setVerifiedCurrent(event.target.checked)} /><span>I verified this is the current syllabus</span></label><button className="secondary-button" onClick={() => void previewSyllabus()} disabled={busy}>{busy ? 'Analyzing…' : 'Preview syllabus'}</button></> : <SyllabusSummary preview={syllabusPreview} onApply={() => void applySyllabus()} busy={busy} />}</section>}
      <div className="import-actions"><button className="quiet-button" onClick={clearSelected}>Cancel</button><button className="primary-button" onClick={() => void importSelected()} disabled={busy}>{busy ? 'Copying…' : `Import ${includedCount} file${includedCount === 1 ? '' : 's'}`}</button></div>
    </section>}
    {results.length > 0 && <section className="success-panel"><strong>{results.length} file{results.length === 1 ? '' : 's'} copied safely.</strong><span>Originals remain in their original locations. {results.some((result) => result.review_item_id) ? 'The uncertain copies remain available for an authorized external agent.' : 'The copies are now in local intake.'}</span></section>}
    {error && <p className="setup-error" role="alert">{error}</p>}
  </div>
}

function SyllabusSummary({ preview, onApply, busy }: { preview: ExtractionPreview; onApply: () => void; busy: boolean }) {
  const candidates = preview.extraction.candidates
  const count = (kind: string) => candidates.filter((candidate) => candidate.kind === kind).length
  const needsExternalAttention = preview.extraction.warnings.length + preview.reconciliation.conflict_count
  return <div className="extraction-summary"><p className="evidence-line"><span>Source · {basename(preview.extraction.source.path)}</span><b>{preview.extraction.source.extraction_method}</b></p><div className="extraction-counts"><span><strong>{count('assignment')}</strong> assignments</span><span><strong>{count('deadline')}</strong> deadlines</span><span><strong>{count('required_reading')}</strong> required readings</span><span><strong>{count('course_meeting')}</strong> weekly meeting times</span></div>{needsExternalAttention > 0 && <p className="review-callout">External-agent attention: {needsExternalAttention} finding{needsExternalAttention === 1 ? '' : 's'} were preserved with the source.</p>}{preview.extraction.warnings.length > 0 && <ul className="extraction-warnings">{preview.extraction.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}<p className="extraction-safe-note">{preview.applied ? 'Supported information was added to derived local state. The source file remains untouched.' : 'Nothing has been changed yet.'}</p><div className="decision-row">{!preview.applied && <button className="primary-button" onClick={onApply} disabled={busy}>{busy ? 'Adding…' : 'Add supported information'}</button>}</div></div>
}

function isSyllabusPath(path: string) { return /\.(pdf|md|markdown|txt)$/i.test(path) }
function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function basename(path: string) { return path.split(/[\\/]/).pop() || path }
function fileKey(file: File) { return `${file.name}\u0000${file.size}\u0000${file.lastModified}` }
function suggestCourse(path: string, courses: Course[]) {
  const name = basename(path).toLowerCase().replace(/[^a-z0-9]+/g, ' ')
  return courses.find((course) => {
    const code = course.code.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
    return code.length > 2 && name.includes(code)
  })
}
