import { ImportView } from './ImportView'
import { MigrationView } from './MigrationView'
import type { Course, StatusPayload } from './types'

type ActionPanelProps = {
  mode: 'import' | 'migration'
  status: StatusPayload
  courses: Course[]
  semester: string
  onModeChange: (mode: 'import' | 'migration') => void
  onClose: () => void
  onImported: () => Promise<void>
  onMigrated: () => Promise<void>
  onBusyChange: (busy: boolean) => void
}

export function ActionPanel({ mode, status, courses, semester, onModeChange, onClose, onImported, onMigrated, onBusyChange }: ActionPanelProps) {
  return <div className="action-panel-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="action-panel" role="dialog" aria-modal="true" aria-labelledby="action-panel-title">
      <header className="action-panel-header"><div className="action-panel-heading"><p className="eyebrow">Workspace actions</p><h2 id="action-panel-title">Bring material into Academia OS</h2><p>Choose one local action. Originals remain preserved unless you explicitly approve a migration move.</p></div><button className="icon-button" aria-label="Close workspace actions" onClick={onClose}>×</button></header>
      <div className="action-panel-tabs"><button className={mode === 'import' ? 'active' : ''} onClick={() => onModeChange('import')}>Import material</button><button className={mode === 'migration' ? 'active' : ''} onClick={() => onModeChange('migration')}>Migrate older material</button></div>
      <div className="action-panel-body">{mode === 'import' ? <ImportView status={status} courses={courses} semester={semester} onImported={onImported} /> : <MigrationView status={status} onApplied={onMigrated} onBusyChange={onBusyChange} />}</div>
    </section>
  </div>
}
