import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import './study-mind-map.css'

export type MindMapCitation = { id: string; source_name: string; locator: string; text: string }
export type MindMapItem = { id: string; topic: string; prompt: string; answer?: string; explanation?: string; citations?: MindMapCitation[] }
export type MindMapConnection = { from: string; to: string; label: string }

type Props = { title: string; rootLabel: string; items: MindMapItem[]; connections?: MindMapConnection[]; startExpanded?: boolean }
type PositionedNode = { id: string; kind: 'root' | 'branch' | 'concept'; tier?: 'main' | 'subpoint'; label: string; x: number; y: number; width: number; height: number; parentId?: string; canExpand?: boolean; isExpanded?: boolean }
type Link = { from: PositionedNode; to: PositionedNode }
type TreeNode = { id: string; kind: 'branch' | 'concept'; label: string; children: TreeNode[] }

const ROW_HEIGHT = 92
const ROOT_X = 140
const FIRST_COLUMN_X = 500
const COLUMN_GAP = 330
const NODE_WIDTH = 250
const MIN_ZOOM = .35
const MAX_ZOOM = 2.5
const ZOOM_STEP = .15

function compactLabel(value: string, maxWords = 7, maxLength = 54) {
  const firstThought = value.trim().split(/(?<=[.!?])\s+/)[0] || value.trim()
  const words = firstThought.split(/\s+/)
  let label = words.slice(0, maxWords).join(' ')
  if (words.length > maxWords) label += '…'
  if (label.length <= maxLength) return label
  const withoutEllipsis = label.replace(/…$/, '')
  const cutoff = withoutEllipsis.slice(0, maxLength - 1).lastIndexOf(' ')
  return `${withoutEllipsis.slice(0, cutoff > 18 ? cutoff : maxLength - 1).trimEnd()}…`
}

function buildTree(items: MindMapItem[], connections: MindMapConnection[]): TreeNode[] {
  const byId = new Map(items.map((item) => [item.id, item]))
  const children = new Map<string, string[]>()
  const parent = new Map<string, string>()
  const hasConnections = connections.some((edge) => byId.has(edge.from) && byId.has(edge.to) && edge.from !== edge.to)

  if (hasConnections) {
    for (const edge of connections) {
      if (!byId.has(edge.from) || !byId.has(edge.to) || edge.from === edge.to || parent.has(edge.to)) continue
      // Keep the map a tree even if generated data contains a cycle or cross-link.
      let ancestor: string | undefined = edge.from
      let createsCycle = false
      while (ancestor) {
        if (ancestor === edge.to) { createsCycle = true; break }
        ancestor = parent.get(ancestor)
      }
      if (createsCycle) continue
      parent.set(edge.to, edge.from)
      children.set(edge.from, [...(children.get(edge.from) ?? []), edge.to])
    }

    const create = (id: string, path = new Set<string>()): TreeNode | null => {
      const item = byId.get(id)
      if (!item || path.has(id)) return null
      const nextPath = new Set(path).add(id)
      return {
        id: item.id, kind: 'concept', label: compactLabel(item.prompt || item.answer || item.topic || 'Core idea'),
        children: (children.get(id) ?? []).map((childId) => create(childId, nextPath)).filter((node): node is TreeNode => Boolean(node)),
      }
    }
    return items.filter((item) => !parent.has(item.id)).map((item) => create(item.id)).filter((node): node is TreeNode => Boolean(node))
  }

  // Older mind maps have no explicit edges. Preserve their topic grouping and
  // make each topic expandable into its concepts.
  const groups = new Map<string, MindMapItem[]>()
  for (const item of items) {
    const key = (item.topic.trim() || 'Key ideas').toLocaleLowerCase()
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  return [...groups].map(([key, group]) => {
    const label = group[0].topic.trim() || 'Key ideas'
    return {
      id: `topic:${key}`, kind: 'branch' as const, label: compactLabel(label),
      children: group.map((item) => ({ id: item.id, kind: 'concept' as const, label: compactLabel(item.prompt || item.answer || item.topic || 'Core idea'), children: [] })),
    }
  })
}

function layoutMap(rootLabel: string, items: MindMapItem[], connections: MindMapConnection[], expandedNodes: Set<string>) {
  const forest = buildTree(items, connections)
  const links: Link[] = []
  const visibleNodes: PositionedNode[] = []
  let row = 0
  let deepestColumn = 0

  const place = (tree: TreeNode, depth: number, parentId?: string): PositionedNode => {
    const childrenVisible = tree.children.length > 0 && expandedNodes.has(tree.id)
    const children = childrenVisible ? tree.children.map((child) => place(child, depth + 1, tree.id)) : []
    const y = children.length
      ? children.reduce((sum, child) => sum + child.y, 0) / children.length
      : 52 + row++ * ROW_HEIGHT
    const node: PositionedNode = {
      id: tree.id, kind: tree.kind, tier: depth === 1 ? 'main' : 'subpoint', label: tree.label,
      x: FIRST_COLUMN_X + (depth - 1) * COLUMN_GAP, y, width: NODE_WIDTH, height: 68,
      parentId, canExpand: tree.children.length > 0, isExpanded: childrenVisible,
    }
    deepestColumn = Math.max(deepestColumn, depth)
    visibleNodes.push(node)
    for (const child of children) links.push({ from: node, to: child })
    return node
  }

  const rootChildren = forest.map((tree) => place(tree, 1))
  const height = Math.max(192, row * ROW_HEIGHT + 72)
  const root: PositionedNode = {
    id: 'map-root', kind: 'root', label: compactLabel(rootLabel, 5, 42), x: ROOT_X,
    y: rootChildren.length ? rootChildren.reduce((sum, node) => sum + node.y, 0) / rootChildren.length : height / 2,
    width: 194, height: 66,
  }
  for (const child of rootChildren) links.push({ from: root, to: child })
  const width = Math.max(710, FIRST_COLUMN_X + (deepestColumn - 1) * COLUMN_GAP + NODE_WIDTH / 2 + 52)
  return { root, nodes: visibleNodes, links, width, height }
}

function connectionPath(link: Link) {
  const { from, to } = link
  const startX = from.x + from.width / 2
  const endX = to.x - to.width / 2
  const bend = Math.max(44, (endX - startX) * .52)
  return `M ${startX} ${from.y} C ${startX + bend} ${from.y}, ${endX - bend} ${to.y}, ${endX} ${to.y}`
}

function MapNode({ node, onToggle }: { node: PositionedNode; onToggle?: (id: string) => void }) {
  const x = node.x - node.width / 2
  const y = node.y - node.height / 2
  return <g data-map-node-id={node.id} className={`study-map-node ${node.kind}${node.tier ? ` ${node.tier}` : ''}${node.parentId ? ' entering' : ''}`} transform={`translate(${x},${y})`}>
    <rect width={node.width} height={node.height} rx={node.kind === 'root' ? 17 : 12} />
    <foreignObject x="0" y="0" width={node.width} height={node.height}>
      <div className="study-map-node-content">
        <strong>{node.label}</strong>
      </div>
    </foreignObject>
    {node.canExpand && <foreignObject className="study-map-toggle-foreign" x={node.width + 8} y={(node.height - 28) / 2} width="30" height="28">
      <button
        className="study-map-toggle"
        type="button"
        aria-expanded={Boolean(node.isExpanded)}
        aria-label={`${node.isExpanded ? 'Hide' : 'Show'} connected ideas for ${node.label}`}
        title={`${node.isExpanded ? 'Hide' : 'Show'} connected ideas`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => { event.stopPropagation(); onToggle?.(node.id) }}
      >{node.isExpanded ? '‹' : '›'}</button>
    </foreignObject>}
  </g>
}

export function StudyMindMap({ title, rootLabel, items, connections = [], startExpanded = false }: Props) {
  const [expanded, setExpanded] = useState(startExpanded)
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(() => new Set())
  const [zoom, setZoom] = useState(1)
  const [panning, setPanning] = useState(false)
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 })
  const viewportRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; scrollLeft: number; scrollTop: number } | null>(null)
  const pendingZoomAnchorRef = useRef<{ logicalX: number; logicalY: number; screenX: number; screenY: number } | null>(null)
  const pendingRevealRef = useRef<string | null>(null)
  const fittedMapKeyRef = useRef('')
  const fitZoomRef = useRef(1)
  const map = useMemo(() => layoutMap(rootLabel, items, connections, expandedNodes), [rootLabel, items, connections, expandedNodes])
  const mapKey = `${rootLabel}:${items.map((item) => item.id).join(',')}`
  const stageWidth = Math.max(viewportSize.width, map.width * zoom)
  const stageHeight = Math.max(viewportSize.height, map.height * zoom)
  const mapOffsetX = (stageWidth - map.width * zoom) / 2
  const mapOffsetY = (stageHeight - map.height * zoom) / 2

  const zoomTo = (value: number, screenPoint?: { x: number; y: number }) => {
    const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, value))
    const viewport = viewportRef.current
    if (viewport && next !== zoom) {
      const screenX = screenPoint?.x ?? viewport.clientWidth / 2
      const screenY = screenPoint?.y ?? viewport.clientHeight / 2
      const currentOffsetX = mapOffsetX - viewport.scrollLeft
      const currentOffsetY = mapOffsetY - viewport.scrollTop
      pendingZoomAnchorRef.current = {
        logicalX: (screenX - currentOffsetX) / zoom,
        logicalY: (screenY - currentOffsetY) / zoom,
        screenX,
        screenY,
      }
    }
    setZoom(next)
  }
  const fitToCanvas = () => {
    const viewport = viewportRef.current
    if (!viewport) return
    const fit = Math.max(MIN_ZOOM, Math.min(1, (viewport.clientWidth - 48) / map.width, (viewport.clientHeight - 48) / map.height))
    fitZoomRef.current = fit
    zoomTo(fit)
  }

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    const anchor = pendingZoomAnchorRef.current
    if (!viewport || !anchor) return
    viewport.scrollLeft = Math.max(0, Math.max(0, (viewport.clientWidth - map.width * zoom) / 2) + anchor.logicalX * zoom - anchor.screenX)
    viewport.scrollTop = Math.max(0, Math.max(0, (viewport.clientHeight - map.height * zoom) / 2) + anchor.logicalY * zoom - anchor.screenY)
    pendingZoomAnchorRef.current = null
  }, [map.height, map.width, zoom])

  useLayoutEffect(() => {
    const parentId = pendingRevealRef.current
    const viewport = viewportRef.current
    if (!parentId || !viewport) return
    const parent = map.nodes.find((node) => node.id === parentId)
    const children = map.nodes.filter((node) => node.parentId === parentId)
    if (!parent || !children.length) return
    const centerX = mapOffsetX + ((parent.x + children[0].x) / 2) * zoom
    const centerY = mapOffsetY + (children.reduce((sum, child) => sum + child.y, 0) / children.length) * zoom
    viewport.scrollTo({
      left: centerX - viewport.clientWidth / 2,
      top: centerY - viewport.clientHeight / 2,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    })
    pendingRevealRef.current = null
  }, [map.nodes, mapOffsetX, mapOffsetY, stageHeight, stageWidth, zoom])

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const measure = () => setViewportSize({ width: viewport.clientWidth, height: viewport.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport || !viewportSize.width || !viewportSize.height || fittedMapKeyRef.current === mapKey) return
    const fit = Math.min(1, (viewport.clientWidth - 48) / map.width, (viewport.clientHeight - 48) / map.height)
    const initialZoom = Math.max(MIN_ZOOM, fit)
    fitZoomRef.current = initialZoom
    fittedMapKeyRef.current = mapKey
    setZoom(initialZoom)
  }, [map.height, map.width, mapKey, viewportSize.height, viewportSize.width])

  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const onWheel = (event: WheelEvent) => {
      // Trackpad pinch gestures are exposed by Chromium and WebKit as a
      // ctrl/meta-wheel. Ordinary two-finger scrolling stays native panning.
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const rect = viewport.getBoundingClientRect()
      const factor = Math.exp(-event.deltaY * .01)
      zoomTo(zoom * factor, { x: event.clientX - rect.left, y: event.clientY - rect.top })
    }
    viewport.addEventListener('wheel', onWheel, { passive: false })
    return () => viewport.removeEventListener('wheel', onWheel)
  }, [map.height, map.width, viewportSize.height, viewportSize.width, zoom])

  useEffect(() => {
    if (!expanded) return
    const oldOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      document.body.style.overflow = oldOverflow
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [expanded])

  const beginPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    const viewport = viewportRef.current
    if (!viewport) return
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, scrollLeft: viewport.scrollLeft, scrollTop: viewport.scrollTop }
    viewport.setPointerCapture(event.pointerId)
    setPanning(true)
  }
  const movePan = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    const viewport = viewportRef.current
    if (!drag || !viewport || drag.pointerId !== event.pointerId) return
    viewport.scrollLeft = drag.scrollLeft - (event.clientX - drag.startX)
    viewport.scrollTop = drag.scrollTop - (event.clientY - drag.startY)
  }
  const endPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return
    dragRef.current = null
    if (viewportRef.current?.hasPointerCapture(event.pointerId)) viewportRef.current.releasePointerCapture(event.pointerId)
    setPanning(false)
  }
  const toggleNode = (id: string) => {
    setExpandedNodes((current) => {
      const next = new Set(current)
      if (next.has(id)) {
        next.delete(id)
        return next
      }
      pendingRevealRef.current = id
      next.add(id)
      return next
    })
  }

  const visualization: ReactNode = items.length ? <div ref={viewportRef} className={`study-map-canvas-wrap${panning ? ' panning' : ''}`} onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan}>
    <div className="study-map-stage" style={{ width: `${stageWidth}px`, height: `${stageHeight}px` }}>
      <svg className="study-map-diagram" width={map.width * zoom} height={map.height * zoom} viewBox={`0 0 ${map.width} ${map.height}`} role="group" aria-label={`Mind map with ${items.length} core ideas about ${rootLabel}`}>
        <title>{title}</title>
        {map.links.map((link, index) => <path className={`study-map-link${link.to.parentId ? ' entering' : ''}`} d={connectionPath(link)} key={`${link.from.id}-${link.to.id}-${index}`} />)}
        <MapNode node={map.root} />
        {map.nodes.map((node) => <MapNode key={node.id} node={node} onToggle={toggleNode} />)}
      </svg>
    </div>
  </div> : <div className="study-map-empty">This map has no concepts to display.</div>

  const content = <div className={`study-map-content${expanded ? ' expanded' : ''}`}>
    <header className="study-map-toolbar"><div><p className="eyebrow">Mind map</p><h3>{title}</h3><small>{items.length} core ideas · expand arrows to follow connected ideas</small></div><div className="study-map-controls"><button type="button" onClick={() => zoomTo(zoom - ZOOM_STEP)} aria-label="Zoom out">−</button><button type="button" className="study-map-zoom-reset" onClick={fitToCanvas} aria-label="Fit mind map to canvas">Fit</button><button type="button" onClick={() => zoomTo(zoom + ZOOM_STEP)} aria-label="Zoom in">+</button>{expanded ? <button type="button" onClick={() => setExpanded(false)}>Close map</button> : <button type="button" onClick={() => setExpanded(true)}>Expand map</button>}</div></header>
    {items.length > 0 && <small className="study-map-gesture-hint">Click an arrow to reveal connected ideas · pinch to zoom · drag or two-finger scroll to move</small>}{visualization}
  </div>

  return expanded ? <div className="study-map-overlay" role="dialog" aria-modal="true" aria-label={title}>{content}</div> : content
}
