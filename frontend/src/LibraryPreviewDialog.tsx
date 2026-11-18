import { Suspense, useEffect, useState } from 'react'
import { DocumentReader } from './DocumentReader'
import { api, fileUrl, isTauriEnvironment } from './lib/api'
import type { FilePreview, LibraryItem } from './types'

export function LibraryPreviewDialog({ item, onClose }: { item: LibraryItem | null; onClose: () => void }) {
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

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
