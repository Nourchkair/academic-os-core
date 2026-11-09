import { useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import type { FilePreview } from './types'
import 'katex/dist/katex.min.css'
import './document-reader.css'

type ReaderMode = 'reader' | 'source'

export function DocumentReader({ preview, assetUrl, emptyMessage }: { preview: FilePreview; assetUrl?: string; emptyMessage: string }) {
  const [mode, setMode] = useState<ReaderMode>('reader')
  const extension = preview.extension.toLowerCase()
  const markdown = extension === '.md' || extension === '.markdown'
  const isCsv = extension === '.csv'
  const isJson = extension === '.json'

  if (preview.kind === 'image') {
    const source = assetUrl || preview.image_data_url
    return source
      ? <figure className="document-image-viewer"><img src={source} alt={preview.name} /><figcaption>{preview.name} · Original image · unchanged</figcaption></figure>
      : <div className="document-empty">{emptyMessage}</div>
  }
  if (!preview.content.trim() && !assetUrl) return <div className="document-empty">{emptyMessage}</div>
  if (preview.kind === 'pdf' && assetUrl) {
    return <iframe className="pdf-preview-frame document-pdf-frame" src={assetUrl} title={`Preview of ${preview.name}`} />
  }
  if (preview.kind === 'pdf') {
    return <div className="document-reader-scroll"><div className="document-prose document-pdf-text"><p className="document-extracted-note">Text extracted from this PDF. Page layout and scanned images are not included in this view.</p><ReadableText content={preview.content} /></div></div>
  }
  if (markdown) {
    return <div className="document-reader-shell">
      <div className="document-reader-toolbar" role="tablist" aria-label="Document view">
        <button className={mode === 'reader' ? 'active' : ''} role="tab" aria-selected={mode === 'reader'} onClick={() => setMode('reader')}>Reader</button>
        <button className={mode === 'source' ? 'active' : ''} role="tab" aria-selected={mode === 'source'} onClick={() => setMode('source')}>Source</button>
        <span>Markdown · original preserved</span>
      </div>
      {mode === 'source'
        ? <pre className="document-source">{preview.content || emptyMessage}</pre>
        : <div className="document-reader-scroll"><article className="document-prose"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={markdownComponents}>{preview.content}</ReactMarkdown></article></div>}
    </div>
  }
  if (isCsv) return <CsvReader content={preview.content} />
  if (isJson) return <JsonReader content={preview.content} />
  return <div className="document-reader-scroll"><article className="document-prose"><ReadableText content={preview.content} /></article></div>
}

const markdownComponents: Components = {
  a: ({ href, children }) => href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    : <span>{children}</span>,
  // Do not fetch images embedded in a document automatically; show their captions instead.
  img: ({ alt }) => <span className="document-image-note">{alt || 'Embedded image'} · open the original file to view</span>,
}

function ReadableText({ content }: { content: string }) {
  return <>{content.split(/\n\s*\n/).map((paragraph, index) => {
    const lines = paragraph.split('\n')
    return <p key={index}>{lines.map((line, lineIndex) => <span key={lineIndex}>{line}{lineIndex < lines.length - 1 && <br />}</span>)}</p>
  })}</>
}

function CsvReader({ content }: { content: string }) {
  const rows = parseCsv(content)
  if (!rows.length) return <div className="document-empty">No rows were found in this CSV file.</div>
  const columns = rows[0].slice(0, 30)
  const visibleRows = rows.slice(1, 201)
  return <div className="document-table-wrap"><table className="document-table"><thead><tr>{columns.map((cell, index) => <th key={index} scope="col">{cell || `Column ${index + 1}`}</th>)}</tr></thead><tbody>{visibleRows.map((row, rowIndex) => <tr key={rowIndex}>{columns.map((_, columnIndex) => <td key={columnIndex}>{row[columnIndex] || ''}</td>)}</tr>)}</tbody></table>{(rows.length > 201 || rows.some((row) => row.length > 30)) && <p className="document-reader-note">Showing up to 200 rows and 30 columns in the reader.</p>}</div>
}

function parseCsv(input: string) {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < input.length; i += 1) {
    const char = input[i]
    if (quoted) {
      if (char === '"' && input[i + 1] === '"') { cell += '"'; i += 1 }
      else if (char === '"') quoted = false
      else cell += char
    } else if (char === '"' && !cell) quoted = true
    else if (char === ',') { row.push(cell); cell = '' }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && input[i + 1] === '\n') i += 1
      row.push(cell); cell = ''
      if (row.some((value) => value.length) || rows.length) rows.push(row)
      row = []
    } else cell += char
  }
  if (cell.length || row.length) { row.push(cell); rows.push(row) }
  return rows
}

function JsonReader({ content }: { content: string }) {
  let value: unknown
  try {
    value = JSON.parse(content)
  } catch {
    return <div className="document-reader-scroll"><article className="document-prose"><p>This JSON file could not be parsed, so its contents are shown as text.</p><pre className="document-source">{content}</pre></article></div>
  }
  return <div className="document-json-root"><JsonValue label="Document" value={value} depth={0} /></div>
}

function JsonValue({ label, value, depth }: { label: string; value: unknown; depth: number }) {
  if (Array.isArray(value) || (typeof value === 'object' && value !== null)) {
    const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item] as const) : Object.entries(value as Record<string, unknown>)
    const kind = Array.isArray(value) ? 'items' : 'fields'
    if (depth >= 8) return <div className="document-json-leaf"><span>{label}</span><code>{Array.isArray(value) ? `Array · ${entries.length} ${kind}` : `Object · ${entries.length} ${kind}`}</code></div>
    return <details className="document-json-group" open={depth < 2}>
      <summary>{label}<small>{Array.isArray(value) ? `${entries.length} ${kind}` : `${entries.length} ${kind}`}</small></summary>
      <div className="document-json-children">{entries.slice(0, 300).map(([key, child]) => <JsonValue key={key} label={Array.isArray(value) ? `[${key}]` : key} value={child} depth={depth + 1} />)}{entries.length > 300 && <p className="document-reader-note">The reader shows the first 300 entries in this section.</p>}</div>
    </details>
  }
  return <div className="document-json-leaf"><span>{label}</span><code>{value === null ? 'null' : typeof value === 'string' ? value : String(value)}</code></div>
}
