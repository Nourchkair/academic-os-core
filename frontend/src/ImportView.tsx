import { useEffect, useMemo, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { getCurrentWebview } from '@tauri-apps/api/webview'
import { api } from './lib/api'
import type { Course, ImportResult, StatusPayload } from './types'

type ImportViewProps = {
  status: StatusPayload
  courses: Course[]
  onImported: () => Promise<void>
}

export function ImportView({ status, courses, onImported }: ImportViewProps) {
  const [paths, setPaths] = useState<string[]>([])
  const [destination, setDestination] = useState('general')
  const [uncertain, setUncertain] = useState(true)
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<ImportResult[]>([])

  useEffect(() => {
    if (!(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__) return
    let unlisten: (() => void) | undefined
    void getCurrentWebview().onDragDropEvent((event) => {
      const payload = event.payload
      if (payload.type === 'enter') setDragging(true)
      if (payload.type === 'leave') setDragging(false)
      if (payload.type === 'drop' && 'paths' in payload) {
        setDragging(false)
        setPaths((current) => Array.from(new Set([...current, ...payload.paths])))
      }
    }).then((stop) => { unlisten = stop })
    return () => unlisten?.()
  }, [])

  const selectedCourse = courses.find((course) => course.id === destination)
  const destinationPath = selectedCourse ? `${selectedCourse.path}/00_INBOX` : `${status.workspace.academic_root}/${status.workspace.semester}/00_INBOX`
  const requiresReview = uncertain || !selectedCourse
  const suggestions = useMemo(() => paths.map((path) => ({ path, course: suggestCourse(path, courses) })), [paths, courses])

  const chooseFiles = async () => {
    try {
      const chosen = await open({ multiple: true, directory: false, title: 'Choose academic material' })
      if (!chosen) return
      const selected = Array.isArray(chosen) ? chosen : [chosen]
      setPaths((current) => Array.from(new Set([...current, ...selected])))
      setError(null)
    } catch (reason) {
      setError(`The file picker could not open: ${String(reason)}`)
    }
  }

  const importSelected = async () => {
    if (!paths.length) {
      setError('Choose or drop at least one file first.')
      return
    }
    try {
      setBusy(true)
      setError(null)
      const imported: ImportResult[] = []
      for (const path of paths) imported.push(await api.importFile(path, destinationPath, requiresReview))
      setResults(imported)
      setPaths([])
      await onImported()
    } catch (reason) {
      setError(`Nothing was moved. The import could not be completed: ${String(reason)}`)
    } finally {
      setBusy(false)
    }
  }

  return <div className="page-stack"><section className="page-intro"><p className="eyebrow">Safe intake</p><h2>Import material</h2><p>Bring in school files without moving the originals. Choose a course when you know it; otherwise send the copy to general intake and let Review help you decide.</p></section><section className={`drop-zone ${dragging ? 'dragging' : ''}`}><div className="drop-icon">↓</div><h3>Drop files here</h3><p>PDFs, documents, slides, notes, or other local academic material.</p><button className="primary-button" onClick={() => void chooseFiles()}>Choose files</button><small>Files are copied into the workspace. The original stays where it is.</small></section>{paths.length > 0 && <section className="import-panel"><div className="section-heading"><div><p className="eyebrow">Selected material</p><h3>{paths.length} file{paths.length === 1 ? '' : 's'} ready</h3></div><button className="quiet-button" onClick={() => setPaths([])}>Clear</button></div><div className="selected-files">{suggestions.map(({ path, course }) => <article className="selected-file" key={path}><div><strong>{basename(path)}</strong><small>{course ? `Likely match: ${course.code} · based on the filename` : 'Course not identified from the filename'}</small></div>{course && <button className="quiet-button" onClick={() => { setDestination(course.id); setUncertain(false) }}>Use suggestion</button>}</article>)}</div><div className="import-options"><label className="setup-field"><span>Destination</span><select value={destination} onChange={(event) => { setDestination(event.target.value); setUncertain(event.target.value === 'general') }}><option value="general">General intake — I’m not sure where this belongs</option>{courses.map((course) => <option value={course.id} key={course.id}>{course.code} · {course.name.split(' - ').slice(1).join(' - ') || course.name}</option>)}</select></label><label className="check-row"><input type="checkbox" checked={uncertain} onChange={(event) => setUncertain(event.target.checked)} /><span>Keep this import in Review until I confirm its destination</span></label></div><div className="preservation-callout"><strong>What will happen</strong><span>Academia OS will copy the selected file into <code>{destinationPath}</code>, preserve the original, create processing state, and record the import in Activity.{requiresReview ? ' Because the destination is uncertain, a Review item will also be created.' : ''}</span></div><button className="primary-button" disabled={busy} onClick={() => void importSelected()}>{busy ? 'Importing…' : `Import ${paths.length} file${paths.length === 1 ? '' : 's'}`}</button></section>}{results.length > 0 && <section className="import-results"><p className="eyebrow">Added safely</p><h3>{results.length} file{results.length === 1 ? '' : 's'} copied into your workspace</h3>{results.map((result) => <div className="result-row" key={result.destination}><span className="result-check">✓</span><div><strong>{basename(result.destination)}</strong><small>Original preserved · {result.review_item_id ? 'Review item created' : 'Ready for processing'}</small></div></div>)}<button className="secondary-button" onClick={() => setResults([])}>Import more material</button></section>}{error && <p className="connection-error" role="alert">{error}</p>}</div>
}

function basename(path: string) { return path.split(/[\\/]/).pop() || path }

function suggestCourse(path: string, courses: Course[]) {
  const name = basename(path).toLowerCase().replace(/[^a-z0-9]+/g, ' ')
  return courses.find((course) => {
    const code = course.code.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
    return code.length > 2 && name.includes(code)
  })
}
