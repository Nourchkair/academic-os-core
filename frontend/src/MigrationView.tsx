import { useEffect, useRef, useState } from 'react'
import { open } from '@tauri-apps/plugin-dialog'
import { api, isTauriEnvironment } from './lib/api'
import type { MigrationExecuteResult, MigrationItem, MigrationPlanResult, MigrationStatusResult, StatusPayload } from './types'

type MigrationViewProps = {
  status: StatusPayload
  onApplied: () => Promise<void>
  onBusyChange: (busy: boolean) => void
}

type MigrationStage = 'choose' | 'scanning' | 'preview' | 'executing' | 'complete'

type GroupedItems = [string, Array<{ item: MigrationItem; index: number }>]

export function MigrationView({ status, onApplied, onBusyChange }: MigrationViewProps) {
  const [stage, setStage] = useState<MigrationStage>('choose')
  const [sourcePath, setSourcePath] = useState('')
  const [plan, setPlan] = useState<MigrationPlanResult | null>(null)
  const [planStatus, setPlanStatus] = useState<MigrationStatusResult | null>(null)
  const [selectedIndexes, setSelectedIndexes] = useState<Set<number>>(new Set())
  const [moveEnabled, setMoveEnabled] = useState(false)
  const [moveAcknowledged, setMoveAcknowledged] = useState(false)
  const [moveDialogOpen, setMoveDialogOpen] = useState(false)
  const [result, setResult] = useState<MigrationExecuteResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const busyRef = useRef(false)
  const pickerOpenRef = useRef(false)
  const sourcePathRef = useRef(sourcePath)
  const scanRequestRef = useRef(0)
  const tauriEnvironment = isTauriEnvironment()

  const setMigrationBusy = (next: boolean) => {
    busyRef.current = next
    setBusy(next)
    onBusyChange(next)
  }

  useEffect(() => () => {
    if (busyRef.current) onBusyChange(false)
  }, [onBusyChange])

  const updateSourcePath = (value: string) => {
    if (busyRef.current) return
    sourcePathRef.current = value
    scanRequestRef.current += 1
    setSourcePath(value)
    setPlan(null)
    setPlanStatus(null)
    setStage('choose')
    setError(null)
  }

  const chooseSource = async () => {
    if (!tauriEnvironment) {
      setError('Browser mode requires a local folder path. Enter it above; native folder selection is available in the Tauri app.')
      return
    }
    if (busyRef.current || pickerOpenRef.current) return
    pickerOpenRef.current = true
    setMigrationBusy(true)
    try {
      const chosen = await open({ directory: true, multiple: false, title: 'Choose an older academic folder' })
      const selected = Array.isArray(chosen) ? chosen[0] : chosen
      if (!selected) return
      sourcePathRef.current = selected
      scanRequestRef.current += 1
      setSourcePath(selected)
      setPlan(null)
      setPlanStatus(null)
      setResult(null)
      setSelectedIndexes(new Set())
      setMoveEnabled(false)
      setError(null)
      setStage('choose')
    } catch (reason) {
      setError(`The folder picker could not open: ${String(reason)}`)
    } finally {
      pickerOpenRef.current = false
      setMigrationBusy(false)
    }
  }

  const scanSource = async () => {
    if (busyRef.current) return
    const source = sourcePathRef.current.trim()
    if (!source) {
      setError('Choose an older academic folder before scanning it.')
      return
    }
    const requestId = scanRequestRef.current + 1
    scanRequestRef.current = requestId
    const isCurrentScan = () => scanRequestRef.current === requestId && sourcePathRef.current.trim() === source
    try {
      setMigrationBusy(true)
      setStage('scanning')
      setError(null)
      setResult(null)
      const planned = await api.migrationPlan(source)
      if (!isCurrentScan()) return
      setPlan(planned)
      setSelectedIndexes(new Set(planned.items.map((_item, index) => index)))
      setMoveEnabled(false)
      setMoveAcknowledged(false)

      let statusReadError: unknown = null
      try {
        const nextStatus = await api.migrationStatus(planned.plan_path)
        if (!isCurrentScan()) return
        setPlanStatus(nextStatus)
      } catch (reason) {
        if (!isCurrentScan()) return
        statusReadError = reason
        setPlanStatus(null)
      }
      if (!isCurrentScan()) return
      setStage('preview')
      if (statusReadError) setError(`The scan is ready, but its read-only status could not be loaded: ${String(statusReadError)}`)
    } catch (reason) {
      if (!isCurrentScan()) return
      setPlan(null)
      setPlanStatus(null)
      setSelectedIndexes(new Set())
      setStage('choose')
      setError(`The folder could not be scanned. Nothing was changed: ${String(reason)}`)
    } finally {
      if (scanRequestRef.current === requestId) setMigrationBusy(false)
    }
  }

  const toggleItem = (index: number) => {
    setSelectedIndexes((current) => {
      const next = new Set(current)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const selectAll = () => {
    if (!plan) return
    setSelectedIndexes(new Set(plan.items.map((_item, index) => index)))
  }

  const clearSelection = () => setSelectedIndexes(new Set())

  const applyMigration = async (mode: 'copy' | 'move') => {
    if (busyRef.current || !plan || selectedIndexes.size === 0) return
    setMoveDialogOpen(false)
    setMoveAcknowledged(false)
    try {
      setMigrationBusy(true)
      setStage('executing')
      setError(null)
      const indexes = [...selectedIndexes].sort((left, right) => left - right)
      const applied = await api.migrationExecute(plan.plan_path, indexes, mode, true, mode === 'move')
      setResult(applied)
      setStage('complete')
      if (applied.applied) {
        try {
          await onApplied()
        } catch (reason) {
          setError(`The migration finished, but workspace status could not be refreshed: ${String(reason)}`)
        }
      }
    } catch (reason) {
      setStage('preview')
      setError(`Nothing was changed by this migration attempt: ${String(reason)}`)
    } finally {
      setMigrationBusy(false)
    }
  }

  const startAnotherScan = () => {
    if (busyRef.current) return
    scanRequestRef.current += 1
    sourcePathRef.current = ''
    setStage('choose')
    setSourcePath('')
    setPlan(null)
    setPlanStatus(null)
    setSelectedIndexes(new Set())
    setMoveEnabled(false)
    setMoveAcknowledged(false)
    setMoveDialogOpen(false)
    setResult(null)
    setError(null)
  }

  const selectedCount = selectedIndexes.size
  const groupedItems = plan ? groupItems(plan.items) : []
  const reportPath = planStatus?.report_path

  return <div className="page-stack migration-page">
    <section className="page-intro migration-intro">
      <p className="eyebrow">Safe legacy intake</p>
      <h2>Bring in older material</h2>
      <p>Scan an older academic folder, review every proposed destination, and choose exactly what belongs in your local workspace. Your old folder stays unchanged by default.</p>
    </section>

    <section className="migration-safety-card" aria-label="Migration safety promise">
      <span className="migration-safety-icon" aria-hidden="true">✓</span>
      <div><strong>Copy is always the starting point</strong><p>Academia OS creates a read-only plan first. Originals stay where they are unless you explicitly choose Move for selected files.</p></div>
    </section>

    <section className="migration-source-card">
      <div className="migration-card-heading"><div><p className="eyebrow">Step 1 · Choose a source</p><h3>Where are the older files?</h3></div><span className="migration-step-badge">{sourcePath ? 'Ready to scan' : 'Not selected'}</span></div>
      <p className="migration-muted">Choose a folder, not an individual file. The scan stays local and ignores operational folders and unsafe links.</p>
      <div className={`migration-source-controls ${tauriEnvironment ? '' : 'browser'}`}>
        <label className="migration-path-field"><span>Older academic folder</span><input value={sourcePath} onChange={(event) => updateSourcePath(event.target.value)} disabled={busy} placeholder={tauriEnvironment ? 'Choose a folder on this computer' : 'Enter a local folder path'} aria-describedby="migration-source-help" /></label>
        {tauriEnvironment && <button className="secondary-button" onClick={() => void chooseSource()} disabled={busy}>Choose folder</button>}
        <button className="primary-button" onClick={() => void scanSource()} disabled={busy || !sourcePath.trim()}>{stage === 'scanning' ? 'Scanning…' : 'Scan and preview'}</button>
      </div>
      <p className="migration-field-help" id="migration-source-help">{tauriEnvironment ? 'Native folder selection is available in the Tauri app.' : 'Browser mode requires you to enter a local path; it cannot open a native folder picker.'} The old folder is only read during this step. No files are copied or moved yet.</p>
      <p className="migration-target-hint">Destination workspace: <code>{status.workspace.academic_root}</code> · current semester: <strong>{status.workspace.semester}</strong></p>
    </section>

    {!sourcePath && stage === 'choose' && <section className="migration-empty-state">
      <div className="migration-empty-mark" aria-hidden="true">↓</div><h3>Start with an older folder</h3><p>After you choose one, the CLI will discover eligible files and propose a semester-aware destination for each one.</p>{tauriEnvironment ? <button className="primary-button" onClick={() => void chooseSource()} disabled={busy}>Choose an older folder</button> : <p className="migration-browser-empty-note">Enter a local folder path above to begin. Native folder selection is available in the Tauri app.</p>}
    </section>}

    {stage === 'scanning' && <section className="migration-loading-card" role="status" aria-live="polite"><span className="migration-spinner" aria-hidden="true" /><div><strong>Scanning and creating a review plan…</strong><p>Hashing eligible files and checking proposed destinations. Your old folder remains untouched.</p></div></section>}

    {plan && (stage === 'preview' || stage === 'executing') && <PlanPreview plan={plan} reportPath={reportPath} selectedIndexes={selectedIndexes} selectedCount={selectedCount} moveEnabled={moveEnabled} busy={busy} groupedItems={groupedItems} onToggle={toggleItem} onSelectAll={selectAll} onClear={clearSelection} onMoveEnabled={(enabled) => { setMoveEnabled(enabled); setMoveAcknowledged(false) }} onCopy={() => void applyMigration('copy')} onRequestMove={() => setMoveDialogOpen(true)} />}

    {stage === 'executing' && <section className="migration-loading-card migration-execution-card" role="status" aria-live="polite"><span className="migration-spinner" aria-hidden="true" /><div><strong>Applying your selection…</strong><p>{selectedCount} selected file{selectedCount === 1 ? '' : 's'} are being copied{moveEnabled ? ' or moved after hash verification' : ''}. Do not close the app until the result appears.</p></div></section>}

    {stage === 'complete' && result && <MigrationResult result={result} busy={busy} onStartAnother={startAnotherScan} />}

    {error && <section className="migration-error-card" role="alert"><span className="migration-error-icon" aria-hidden="true">!</span><div><strong>Migration needs your attention</strong><p>{error}</p><button className="quiet-button" onClick={() => setError(null)}>Dismiss</button></div></section>}

    {moveDialogOpen && plan && <MoveConfirmation selectedCount={selectedCount} acknowledged={moveAcknowledged} onAcknowledge={setMoveAcknowledged} onCancel={() => { setMoveDialogOpen(false); setMoveAcknowledged(false) }} onConfirm={() => void applyMigration('move')} />}
  </div>
}

function PlanPreview({ plan, reportPath, selectedIndexes, selectedCount, moveEnabled, busy, groupedItems, onToggle, onSelectAll, onClear, onMoveEnabled, onCopy, onRequestMove }: {
  plan: MigrationPlanResult
  reportPath?: string
  selectedIndexes: Set<number>
  selectedCount: number
  moveEnabled: boolean
  busy: boolean
  groupedItems: GroupedItems[]
  onToggle: (index: number) => void
  onSelectAll: () => void
  onClear: () => void
  onMoveEnabled: (enabled: boolean) => void
  onCopy: () => void
  onRequestMove: () => void
}) {
  const allSelected = plan.items.length > 0 && selectedCount === plan.items.length
  return <>
    <section className="migration-preview-card">
      <div className="migration-card-heading"><div><p className="eyebrow">Step 2 · Read-only preview</p><h3>Review the migration plan</h3></div><span className="migration-ready-badge">Plan ready</span></div>
      <p className="migration-muted">Nothing has been imported. Review the source, destination, and file evidence before choosing any action.</p>
      <div className="migration-summary-grid">
        <MigrationSummary label="Source folder" value={plan.source_root} wide />
        <MigrationSummary label="Academic workspace" value={plan.academic_root} wide />
        <MigrationSummary label="Current semester" value={plan.current_semester} />
        <MigrationSummary label="Files discovered" value={String(plan.item_count)} />
        <MigrationSummary label="Total size" value={formatBytes(plan.total_size)} />
      </div>
      <div className="migration-artifacts"><span className="migration-artifact-label">Review artifacts saved by the CLI</span><div><span>Plan</span><code>{plan.plan_path}</code></div><div><span>Review</span><code>{plan.review_path}</code></div>{reportPath && <div><span>Report</span><code>{reportPath}</code></div>}</div>
    </section>

    <section className="migration-items-card">
      <div className="migration-list-heading"><div><p className="eyebrow">Step 3 · Choose files</p><h3>{selectedCount} of {plan.items.length} selected</h3></div><div className="migration-selection-actions"><button className="quiet-button" onClick={onSelectAll} disabled={busy || allSelected || plan.items.length === 0}>Select all</button><button className="quiet-button" onClick={onClear} disabled={busy || selectedCount === 0}>Clear selection</button></div></div>
      <p className="migration-reviewable-note"><strong>Reviewable intake:</strong> material routed through <code>LEGACY_IMPORT</code> is deliberately left identifiable for later review. Unknown files are not silently classified as a course.</p>
      {plan.items.length === 0 ? <div className="migration-no-files"><strong>No eligible files were found.</strong><span>The old folder remains unchanged. You can scan another folder whenever you are ready.</span></div> : <div className="migration-groups">{groupedItems.map(([semester, items]) => <section className="migration-semester-group" key={semester}><div className="migration-group-heading"><h4>{semester}</h4><span>{items.length} file{items.length === 1 ? '' : 's'}</span></div><div className="migration-file-list">{items.map(({ item, index }) => <MigrationItemRow item={item} index={index} selected={selectedIndexes.has(index)} disabled={busy} onToggle={onToggle} key={`${index}-${item.source}`} />)}</div></section>)}</div>}
    </section>

    <section className="migration-action-card">
      <div className="migration-card-heading"><div><p className="eyebrow">Step 4 · Apply deliberately</p><h3>Bring selected files into your workspace</h3></div><span className="migration-copy-badge">Copy first</span></div>
      <div className="migration-copy-option"><div><strong>Copy selected files</strong><p>Recommended. The source folder and every original file stay unchanged. Copies go to the proposed destinations above.</p></div><button className="primary-button" onClick={onCopy} disabled={busy || selectedCount === 0}>{busy ? 'Working…' : 'Copy selected files'}</button></div>
      <div className={`migration-move-option ${moveEnabled ? 'enabled' : ''}`}><label className="migration-move-toggle"><input type="checkbox" checked={moveEnabled} onChange={(event) => onMoveEnabled(event.target.checked)} disabled={busy || selectedCount === 0} /><span><strong>Optional Move mode</strong><small>Remove only selected originals after the destination hash is verified. Unselected files remain untouched.</small></span></label>{moveEnabled && <div className="migration-move-warning" role="note"><strong>Destructive action</strong><span>Move cannot be undone from Academia OS. You will get one more confirmation before anything is removed.</span></div>}{moveEnabled && <button className="migration-danger-button" onClick={onRequestMove} disabled={busy || selectedCount === 0}>Review move confirmation</button>}</div>
      {selectedCount === 0 && <p className="migration-selection-help" role="status">No files are selected. Actions are disabled, and the old folder remains unchanged.</p>}
      {moveEnabled && selectedCount > 0 && <p className="migration-selection-help">Review the confirmation dialog before moving selected originals. Copy remains available as the safer option.</p>}
    </section>
  </>
}

function MigrationItemRow({ item, index, selected, disabled, onToggle }: { item: MigrationItem; index: number; selected: boolean; disabled: boolean; onToggle: (index: number) => void }) {
  return <article className={`migration-file-row ${selected ? 'selected' : ''}`}>
    <label className="migration-file-check" htmlFor={`migration-file-${index}`}><input id={`migration-file-${index}`} type="checkbox" checked={selected} onChange={() => onToggle(index)} disabled={disabled} aria-label={`Select ${item.relative_path}`} /><span aria-hidden="true" /></label>
    <div className="migration-file-main"><strong title={item.relative_path}>{item.relative_path}</strong><span className="migration-destination-label">Proposed destination</span><code title={item.destination}>{item.destination}</code></div>
    <div className="migration-file-meta"><span>{formatBytes(item.size)}</span><span title={item.sha256}>SHA {item.sha256.slice(0, 12)}…</span><em>LEGACY_IMPORT · reviewable</em></div>
  </article>
}

function MigrationResult({ result, busy, onStartAnother }: { result: MigrationExecuteResult; busy: boolean; onStartAnother: () => void }) {
  const complete = result.status === 'completed'
  const confirmationRequired = result.status === 'confirmation_required'
  const selected = safeCount(result.selected)
  const copied = safeCount(result.copied)
  const moved = safeCount(result.moved)
  const skipped = safeCount(result.skipped)
  const failed = safeCount(result.failed)
  const destinations = Array.isArray(result.destinations) ? result.destinations : []
  const failures = Array.isArray(result.failures) ? result.failures : []
  const copiedOrMoved = copied + moved
  return <section className={`migration-result-card ${complete ? 'complete' : 'partial'}`}>
    <div className="migration-result-heading"><div className="migration-result-mark" aria-hidden="true">{complete ? '✓' : '!'}</div><div><p className="eyebrow">{complete ? 'Migration complete' : confirmationRequired ? 'Confirmation required' : 'Completed with failures'}</p><h3>{complete ? 'Your selected material is in the workspace' : confirmationRequired ? 'The migration is ready for confirmation' : 'Some selected files need another look'}</h3><p>{result.mode === 'copy' ? 'Original files remain in their original locations.' : 'Only selected originals that passed destination hash verification were removed; unselected files remain untouched.'}</p></div></div>
    <div className="migration-result-counts"><MigrationResultCount label="Selected" value={selected} /><MigrationResultCount label="Copied" value={copied} /><MigrationResultCount label="Moved" value={moved} /><MigrationResultCount label="Skipped" value={skipped} /><MigrationResultCount label="Failed" value={failed} /></div>
    <p className="migration-result-summary">{copiedOrMoved} file{copiedOrMoved === 1 ? '' : 's'} reached a proposed destination. The CLI report records this {result.mode} operation.</p>
    <div className="migration-result-columns"><div><h4>Destinations</h4>{destinations.length ? <ul className="migration-result-list">{destinations.map((destination, index) => <li key={`${index}-${destination}`}><code>{destination}</code></li>)}</ul> : <p className="migration-muted">No destination was written.</p>}</div>{failures.length > 0 && <div><h4>Failure details</h4><ul className="migration-failure-list">{failures.map((failure, index) => <li key={`${index}-${failure}`}>{failure}</li>)}</ul></div>}</div>
    <div className="migration-result-artifact"><span>Report</span><code>{result.report_path || 'Report path unavailable'}</code></div>
    <div className="migration-result-actions"><button className="primary-button" onClick={onStartAnother} disabled={busy}>Start another scan</button></div>
  </section>
}

function MoveConfirmation({ selectedCount, acknowledged, onAcknowledge, onCancel, onConfirm }: { selectedCount: number; acknowledged: boolean; onAcknowledge: (value: boolean) => void; onCancel: () => void; onConfirm: () => void }) {
  const dialogRef = useRef<HTMLElement>(null)
  const onCancelRef = useRef(onCancel)
  useEffect(() => {
    onCancelRef.current = onCancel
  }, [onCancel])

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const dialog = dialogRef.current
    if (!dialog) return () => previouslyFocused?.focus()

    const focusable = getFocusableElements(dialog)
    ;(focusable[0] ?? dialog).focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancelRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const controls = getFocusableElements(dialog)
      if (!controls.length) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = controls[0]
      const last = controls[controls.length - 1]
      const current = document.activeElement
      if (event.shiftKey ? current === first || !dialog.contains(current) : current === last || !dialog.contains(current)) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      if (previouslyFocused?.isConnected) previouslyFocused.focus()
    }
  }, [])

  return <div className="migration-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) event.preventDefault() }}><section ref={dialogRef} className="migration-dialog" role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby="move-dialog-title" aria-describedby="move-dialog-description">
    <div className="migration-dialog-icon" aria-hidden="true">!</div><p className="eyebrow">Final confirmation</p><h3 id="move-dialog-title">Move {selectedCount} selected original{selectedCount === 1 ? '' : 's'}?</h3><p id="move-dialog-description">Move is destructive. Academia OS will copy each selected file, verify its hash, and only then remove that original. Files you did not select remain untouched.</p>
    <label className="migration-confirm-check"><input type="checkbox" checked={acknowledged} onChange={(event) => onAcknowledge(event.target.checked)} /><span>I understand that selected originals will be removed after successful verification.</span></label>
    <div className="migration-dialog-actions"><button className="quiet-button" onClick={onCancel}>Keep originals</button><button className="migration-danger-button" onClick={onConfirm} disabled={!acknowledged}>Confirm move</button></div>
  </section></div>
}

function MigrationSummary({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return <div className={`migration-summary-cell ${wide ? 'wide' : ''}`}><span>{label}</span><code title={value}>{value}</code></div>
}

function MigrationResultCount({ label, value }: { label: string; value: number }) {
  return <div><strong>{value}</strong><span>{label}</span></div>
}

function safeCount(value: number | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function getFocusableElements(root: HTMLElement) {
  return Array.from(root.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
}

function groupItems(items: MigrationItem[]): GroupedItems[] {
  const groups = new Map<string, Array<{ item: MigrationItem; index: number }>>()
  items.forEach((item, index) => {
    const group = groups.get(item.semester) ?? []
    group.push({ item, index })
    groups.set(item.semester, group)
  })
  return [...groups.entries()]
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = -1
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}
