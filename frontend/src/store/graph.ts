import {create} from 'zustand'
import type {Edge, Node} from '@xyflow/react'
import type {ChildrenResponse, EdgeResponse, NodeResponse} from '../api/types'
import {styleBundledEdge, styleEdge} from '../canvas/edges/edgeStyles'

const NODE_WIDTH = 220
const NODE_HEIGHT = 72
const GRID_GAP_X = 60
const GRID_GAP_Y = 40
const COMPOUND_PAD = 24
const COMPOUND_HEADER = 60

// Very large finite bound; ReactFlow's extent doesn't accept `Infinity`.
const EXTENT_MAX = 1e7

// ── localStorage helpers ──────────────────────────────────────────────────────

interface PersistedGraphState {
  expanded: string[]
  positions: Record<string, { x: number; y: number }>
}

function lsKey(rootNodeId: string): string {
  return `graph:${rootNodeId}`
}

function saveToStorage(
  rootNodeId: string,
  expanded: Set<string>,
  positions: Map<string, { x: number; y: number }>,
): void {
  try {
    const data: PersistedGraphState = {
      expanded: Array.from(expanded),
      positions: Object.fromEntries(positions),
    }
    localStorage.setItem(lsKey(rootNodeId), JSON.stringify(data))
  } catch {
    // ignore quota errors
  }
}

function loadFromStorage(rootNodeId: string): PersistedGraphState | null {
  try {
    const raw = localStorage.getItem(lsKey(rootNodeId))
    if (!raw) return null
    return JSON.parse(raw) as PersistedGraphState
  } catch {
    return null
  }
}

// ── layout helpers ────────────────────────────────────────────────────────────

function gridLayoutAll(
  parentId: string,
  nodes: Map<string, NodeResponse>,
  positions: Map<string, { x: number; y: number }>,
  userPositioned: Set<string>,
): void {
  const children = Array.from(nodes.values()).filter((n) => n.parentId === parentId)
  if (!children.length) return
  const cols = Math.ceil(Math.sqrt(children.length))
  children.forEach((child, idx) => {
    if (!userPositioned.has(child.id)) {
      positions.set(child.id, {
        x: (idx % cols) * (NODE_WIDTH + GRID_GAP_X) + COMPOUND_PAD,
        y: Math.floor(idx / cols) * (NODE_HEIGHT + GRID_GAP_Y) + COMPOUND_HEADER,
      })
    }
  })
}

/** Place ONLY children that don't yet have a position, below the existing
 *  bottom row. Used after mergeChildren / neighbor fetch so newly arrived
 *  nodes don't all sit at (0,0). */
function placeUnpositionedChildren(
  parentId: string,
  nodes: Map<string, NodeResponse>,
  positions: Map<string, { x: number; y: number }>,
): void {
  const children = Array.from(nodes.values()).filter((n) => n.parentId === parentId)
  if (!children.length) return
  const unplaced = children.filter((c) => !positions.has(c.id))
  if (!unplaced.length) return

  let bottomY = COMPOUND_HEADER
  let rightX = COMPOUND_PAD
  for (const c of children) {
    const pos = positions.get(c.id)
    if (!pos) continue
    bottomY = Math.max(bottomY, pos.y + NODE_HEIGHT + GRID_GAP_Y)
    rightX = Math.max(rightX, pos.x + NODE_WIDTH)
  }

  const cols = Math.max(1, Math.ceil(Math.sqrt(unplaced.length)))
  unplaced.forEach((child, idx) => {
    positions.set(child.id, {
      x: (idx % cols) * (NODE_WIDTH + GRID_GAP_X) + COMPOUND_PAD,
      y: Math.floor(idx / cols) * (NODE_HEIGHT + GRID_GAP_Y) + bottomY,
    })
  })
}

// ── pure flow computation ─────────────────────────────────────────────────────

function computeFlowNodes(
  nodes: Map<string, NodeResponse>,
  expanded: Set<string>,
  positions: Map<string, { x: number; y: number }>,
  rootNodeId: string | null,
): Node[] {
  // Visibility: root + every node whose parent is expanded AND loaded.
  const visible = new Set<string>()
  nodes.forEach((node) => {
    const isRoot = node.id === rootNodeId
    const isVisible = isRoot || (node.parentId !== null && expanded.has(node.parentId))
    if (isVisible) visible.add(node.id)
  })

  const childrenOfCompound = new Map<string, NodeResponse[]>()
  nodes.forEach((node) => {
    if (node.parentId && visible.has(node.id) && visible.has(node.parentId)) {
      const arr = childrenOfCompound.get(node.parentId) ?? []
      arr.push(node)
      childrenOfCompound.set(node.parentId, arr)
    }
  })

  // Bottom-up: compound parents are sized to enclose child bbox.
  const sizes = new Map<string, { width: number; height: number }>()
  const isCompoundId = (id: string): boolean => {
    if (!expanded.has(id)) return false
    const kids = childrenOfCompound.get(id)
    return !!(kids && kids.length > 0)
  }
  const getSize = (nodeId: string): { width: number; height: number } => {
    const cached = sizes.get(nodeId)
    if (cached) return cached
    if (!isCompoundId(nodeId)) {
      const s = { width: NODE_WIDTH, height: NODE_HEIGHT }
      sizes.set(nodeId, s)
      return s
    }
    const kids = childrenOfCompound.get(nodeId) ?? []
    let maxRight = 0
    let maxBottom = 0
    for (const child of kids) {
      const pos = positions.get(child.id) ?? { x: 0, y: 0 }
      const cs = getSize(child.id)
      maxRight = Math.max(maxRight, pos.x + cs.width)
      maxBottom = Math.max(maxBottom, pos.y + cs.height)
    }
    const s = {
      width: Math.max(NODE_WIDTH + COMPOUND_PAD * 2, maxRight + COMPOUND_PAD),
      height: Math.max(COMPOUND_HEADER + NODE_HEIGHT + COMPOUND_PAD, maxBottom + COMPOUND_PAD),
    }
    sizes.set(nodeId, s)
    return s
  }

  const result: Node[] = []
  nodes.forEach((node) => {
    if (!visible.has(node.id)) return

    const pos = positions.get(node.id) ?? { x: 0, y: 0 }
    const isExpanded = expanded.has(node.id)
    const kids = childrenOfCompound.get(node.id) ?? []
    const hasChildren = kids.length > 0
    const isCompound = isExpanded && hasChildren

    const flowNode: Node = {
      id: node.id,
      position: pos,
      data: { node, isExpanded, hasChildren, isCompound },
      type:
        node.kind === 'directory' ? 'directory'
        : node.kind === 'file' ? 'file'
        : node.kind === 'class' ? 'class'
        : node.kind === 'function' || node.kind === 'method' ? 'function'
        : node.kind === 'external_module' ? 'external'
        : 'default',
    }

    if (isCompound) {
      const s = getSize(node.id)
      flowNode.style = { width: s.width, height: s.height }
    }

    const isRoot = node.id === rootNodeId
    if (!isRoot && node.parentId && expanded.has(node.parentId)) {
      flowNode.parentId = node.parentId
      // Clamp top/left to 0 so children can't escape past the parent corner,
      // but leave bottom/right free so the parent grows as children drag out.
      flowNode.extent = [
        [0, 0],
        [EXTENT_MAX, EXTENT_MAX],
      ]
    }

    result.push(flowNode)
  })
  return result
}

function computeFlowEdges(
  edges: Map<string, EdgeResponse>,
  nodes: Map<string, NodeResponse>,
  expanded: Set<string>,
  rootNodeId: string | null,
  hoveredNodeId: string | null = null,
): Edge[] {
  const visibleIds = new Set<string>()
  nodes.forEach((node) => {
    const isRoot = node.id === rootNodeId
    const isVisible = isRoot || (node.parentId !== null && expanded.has(node.parentId))
    if (isVisible) visibleIds.add(node.id)
  })

  const resolveEndpoint = (nodeId: string): string | null => {
    if (visibleIds.has(nodeId)) return nodeId
    let current = nodes.get(nodeId)
    while (current) {
      if (!current.parentId) return null
      const parent = nodes.get(current.parentId)
      if (!parent) return null
      if (visibleIds.has(parent.id)) return parent.id
      current = parent
    }
    return null
  }

  // Bundle multiple edges between the same (src, tgt) — even of different
  // kinds — into a single rendered edge. We track which kinds and the highest
  // confidence so the bundle can be styled meaningfully.
  interface Bundle {
    src: string
    tgt: string
    kinds: Set<string>
    minConf: number
    sourceIds: string[]
    targetIds: string[]
    rawEdgeId: string
    rawEdge: EdgeResponse
  }
  const bundles = new Map<string, Bundle>()

  edges.forEach((edge) => {
    const src = resolveEndpoint(edge.sourceId)
    const tgt = resolveEndpoint(edge.targetId)
    if (!src || !tgt || src === tgt) return
    const key = `${src}::${tgt}`
    let b = bundles.get(key)
    if (!b) {
      b = {
        src,
        tgt,
        kinds: new Set<string>(),
        minConf: 1,
        sourceIds: [],
        targetIds: [],
        rawEdgeId: edge.id,
        rawEdge: edge,
      }
      bundles.set(key, b)
    }
    b.kinds.add(edge.kind)
    if (edge.confidence < b.minConf) b.minConf = edge.confidence
    b.sourceIds.push(edge.sourceId)
    b.targetIds.push(edge.targetId)
  })

  const result: Edge[] = []
  bundles.forEach((b) => {
    const isBundled = b.kinds.size > 1 || b.sourceIds.length > 1
    const style = isBundled
      ? styleBundledEdge(b.kinds, b.minConf)
      : styleEdge(b.rawEdge)

    let className: string | undefined
    if (hoveredNodeId) {
      const touchesHovered =
        b.sourceIds.includes(hoveredNodeId) ||
        b.targetIds.includes(hoveredNodeId) ||
        b.src === hoveredNodeId ||
        b.tgt === hoveredNodeId
      className = touchesHovered ? 'edge-highlight' : 'edge-dim'
    }

    result.push({
      id: `bundle:${b.src}::${b.tgt}`,
      source: b.src,
      target: b.tgt,
      data: { bundleKinds: Array.from(b.kinds), bundleCount: b.sourceIds.length },
      className,
      ...style,
    })
  })
  return result
}

// ── store ─────────────────────────────────────────────────────────────────────

interface GraphState {
  nodes: Map<string, NodeResponse>
  edges: Map<string, EdgeResponse>
  expanded: Set<string>
  userPositioned: Set<string>
  positions: Map<string, { x: number; y: number }>
  rootNodeId: string | null
  hoveredNodeId: string | null

  flowNodes: Node[]
  flowEdges: Edge[]

  loadRoot: (projectId: string) => Promise<void>
  expand: (nodeId: string) => Promise<void>
  collapse: (nodeId: string) => void
  setNodePosition: (
    nodeId: string,
    position: { x: number; y: number },
    markUserPositioned?: boolean,
  ) => void
  setHoveredNode: (nodeId: string | null) => void
  tidy: () => void
  applyNodeUpsert: (node: NodeResponse) => void
  applyNodeRemove: (id: string) => void
  applyEdgeUpsert: (edge: EdgeResponse) => void
  applyEdgeRemove: (id: string) => void
  reset: () => void
}

const makeEmptyState = () => ({
  nodes: new Map<string, NodeResponse>(),
  edges: new Map<string, EdgeResponse>(),
  expanded: new Set<string>(),
  userPositioned: new Set<string>(),
  positions: new Map<string, { x: number; y: number }>(),
  rootNodeId: null as string | null,
  hoveredNodeId: null as string | null,
  flowNodes: [] as Node[],
  flowEdges: [] as Edge[],
})

export const useGraphStore = create<GraphState>((set, get) => ({
  ...makeEmptyState(),

  loadRoot: async (projectId: string) => {
    const { get: getApi } = await import('../api/client')
    const root = await getApi<NodeResponse>(`/api/project/${projectId}/tree`)

    const nodes = new Map<string, NodeResponse>([[root.id, root]])
    const edges = new Map<string, EdgeResponse>()
    const expanded = new Set<string>()
    const userPositioned = new Set<string>()
    const positions = new Map<string, { x: number; y: number }>([[root.id, { x: 80, y: 80 }]])

    const saved = loadFromStorage(root.id)
    if (saved) {
      saved.expanded.forEach((id) => expanded.add(id))
      Object.entries(saved.positions).forEach(([id, pos]) => {
        positions.set(id, pos)
        userPositioned.add(id)
      })
    }

    set({
      nodes, edges, expanded, userPositioned, positions,
      rootNodeId: root.id,
      hoveredNodeId: null,
      flowNodes: computeFlowNodes(nodes, expanded, positions, root.id),
      flowEdges: computeFlowEdges(edges, nodes, expanded, root.id, null),
    })

    if (saved && saved.expanded.length > 0) {
      const wantExpanded = new Set(saved.expanded)
      const seen = new Set<string>()
      const queue: string[] = [root.id]

      while (queue.length) {
        const nodeId = queue.shift()!
        if (seen.has(nodeId)) continue
        seen.add(nodeId)
        try {
          await mergeChildren(nodeId, get, set)
        } catch {
          continue
        }
        const stateNodes = get().nodes
        stateNodes.forEach((n) => {
          if (n.parentId === nodeId && wantExpanded.has(n.id) && !seen.has(n.id)) {
            queue.push(n.id)
          }
        })
      }
    }
  },

  expand: async (nodeId: string) => {
    const { expanded, positions, userPositioned, rootNodeId } = get()
    if (expanded.has(nodeId)) return

    await mergeChildren(nodeId, get, set)

    const newExpanded = new Set(expanded)
    newExpanded.add(nodeId)
    const newPositions = new Map(positions)
    const newUserPositioned = new Set(userPositioned)
    // Place ALL children of the just-expanded node in a grid (preserving any
    // userPositioned overrides). This is the path taken when the user clicks
    // `+`: we want a clean layout, not a (0,0) pile.
    gridLayoutAll(nodeId, get().nodes, newPositions, newUserPositioned)

    const { nodes, edges, hoveredNodeId } = get()
    set({
      expanded: newExpanded,
      positions: newPositions,
      flowNodes: computeFlowNodes(nodes, newExpanded, newPositions, rootNodeId),
      flowEdges: computeFlowEdges(edges, nodes, newExpanded, rootNodeId, hoveredNodeId),
    })

    if (rootNodeId) saveToStorage(rootNodeId, newExpanded, newPositions)
  },

  collapse: (nodeId: string) => {
    const { expanded, rootNodeId, positions, nodes, edges } = get()
    if (!expanded.has(nodeId)) return

    const newExpanded = new Set(expanded)
    const toRemove = new Set<string>()
    const visit = (id: string) => {
      toRemove.add(id)
      newExpanded.forEach((eid) => {
        const n = nodes.get(eid)
        if (n?.parentId === id) visit(eid)
      })
    }
    visit(nodeId)
    toRemove.forEach((id) => newExpanded.delete(id))

    const { hoveredNodeId } = get()
    set({
      expanded: newExpanded,
      flowNodes: computeFlowNodes(nodes, newExpanded, positions, rootNodeId),
      flowEdges: computeFlowEdges(edges, nodes, newExpanded, rootNodeId, hoveredNodeId),
    })

    if (rootNodeId) saveToStorage(rootNodeId, newExpanded, positions)
  },

  setHoveredNode: (nodeId: string | null) => {
    const cur = get().hoveredNodeId
    if (cur === nodeId) return
    const { nodes, edges, expanded, rootNodeId } = get()
    set({
      hoveredNodeId: nodeId,
      flowEdges: computeFlowEdges(edges, nodes, expanded, rootNodeId, nodeId),
    })
    if (nodeId) {
      void loadNeighborsIfNeeded(nodeId, get, set)
    }
  },

  setNodePosition: (
    nodeId: string,
    position: { x: number; y: number },
    markUserPositioned = true,
  ) => {
    const { userPositioned, positions, rootNodeId, expanded, nodes } = get()
    const newPositions = new Map(positions)
    newPositions.set(nodeId, position)
    let newUserPositioned = userPositioned
    if (markUserPositioned && !userPositioned.has(nodeId)) {
      newUserPositioned = new Set(userPositioned)
      newUserPositioned.add(nodeId)
    }

    set({
      positions: newPositions,
      userPositioned: newUserPositioned,
      flowNodes: computeFlowNodes(nodes, expanded, newPositions, rootNodeId),
    })

    if (markUserPositioned && rootNodeId) {
      saveToStorage(rootNodeId, expanded, newPositions)
    }
  },

  tidy: () => {
    const { nodes, edges, expanded, rootNodeId, hoveredNodeId, positions } = get()
    const newPositions = new Map<string, { x: number; y: number }>()
    if (rootNodeId) {
      newPositions.set(rootNodeId, positions.get(rootNodeId) ?? { x: 80, y: 80 })
    }

    // Build visibility + childrenOfCompound (same rule as computeFlowNodes).
    const visible = new Set<string>()
    nodes.forEach((node) => {
      const isRoot = node.id === rootNodeId
      const isVisible = isRoot || (node.parentId !== null && expanded.has(node.parentId))
      if (isVisible) visible.add(node.id)
    })
    const childrenOf = new Map<string, NodeResponse[]>()
    nodes.forEach((node) => {
      if (node.parentId && visible.has(node.id) && visible.has(node.parentId)) {
        const arr = childrenOf.get(node.parentId) ?? []
        arr.push(node)
        childrenOf.set(node.parentId, arr)
      }
    })

    // Depth from root so we can process compounds leaves-first: when we lay
    // out parent P, every child of P that is itself a compound must already
    // have its size computed.
    const depthOf = (id: string): number => {
      let d = 0
      let cur = nodes.get(id)
      while (cur?.parentId) {
        d++
        cur = nodes.get(cur.parentId)
      }
      return d
    }
    const compounds = Array.from(expanded)
      .filter((id) => (childrenOf.get(id)?.length ?? 0) > 0)
      .sort((a, b) => depthOf(b) - depthOf(a))

    const sizeOf = new Map<string, { width: number; height: number }>()
    const getSize = (id: string): { width: number; height: number } =>
      sizeOf.get(id) ?? { width: NODE_WIDTH, height: NODE_HEIGHT }

    for (const parentId of compounds) {
      const kids = childrenOf.get(parentId) ?? []
      if (!kids.length) continue

      // Cell dimensions = the largest child + gap. Uniform-cell grid is the
      // simplest layout that guarantees no overlap regardless of which kids
      // are themselves expanded compounds.
      let maxW = NODE_WIDTH
      let maxH = NODE_HEIGHT
      for (const k of kids) {
        const sz = getSize(k.id)
        if (sz.width > maxW) maxW = sz.width
        if (sz.height > maxH) maxH = sz.height
      }
      const cellW = maxW + GRID_GAP_X
      const cellH = maxH + GRID_GAP_Y
      const cols = Math.max(1, Math.ceil(Math.sqrt(kids.length)))

      let rightmost = 0
      let bottommost = 0
      kids.forEach((child, idx) => {
        const col = idx % cols
        const row = Math.floor(idx / cols)
        const x = col * cellW + COMPOUND_PAD
        const y = row * cellH + COMPOUND_HEADER
        newPositions.set(child.id, { x, y })
        const cs = getSize(child.id)
        rightmost = Math.max(rightmost, x + cs.width)
        bottommost = Math.max(bottommost, y + cs.height)
      })

      sizeOf.set(parentId, {
        width: Math.max(NODE_WIDTH + COMPOUND_PAD * 2, rightmost + COMPOUND_PAD),
        height: Math.max(COMPOUND_HEADER + NODE_HEIGHT + COMPOUND_PAD, bottommost + COMPOUND_PAD),
      })
    }

    set({
      positions: newPositions,
      userPositioned: new Set<string>(),
      flowNodes: computeFlowNodes(nodes, expanded, newPositions, rootNodeId),
      flowEdges: computeFlowEdges(edges, nodes, expanded, rootNodeId, hoveredNodeId),
    })
    if (rootNodeId) saveToStorage(rootNodeId, expanded, newPositions)
  },

  applyNodeUpsert: (node: NodeResponse) => {
    const { nodes, edges, expanded, positions, rootNodeId, hoveredNodeId } = get()
    const newNodes = new Map(nodes)
    newNodes.set(node.id, node)
    const newPositions = new Map(positions)
    if (node.parentId && expanded.has(node.parentId)) {
      placeUnpositionedChildren(node.parentId, newNodes, newPositions)
    }
    set({
      nodes: newNodes,
      positions: newPositions,
      flowNodes: computeFlowNodes(newNodes, expanded, newPositions, rootNodeId),
      flowEdges: computeFlowEdges(edges, newNodes, expanded, rootNodeId, hoveredNodeId),
    })
  },

  applyNodeRemove: (id: string) => {
    const { nodes, edges, expanded, positions, rootNodeId, hoveredNodeId } = get()
    if (!nodes.has(id)) return
    const newNodes = new Map(nodes)
    newNodes.delete(id)
    const newEdges = new Map(edges)
    edges.forEach((e, k) => {
      if (e.sourceId === id || e.targetId === id) newEdges.delete(k)
    })
    set({
      nodes: newNodes,
      edges: newEdges,
      flowNodes: computeFlowNodes(newNodes, expanded, positions, rootNodeId),
      flowEdges: computeFlowEdges(newEdges, newNodes, expanded, rootNodeId, hoveredNodeId),
    })
  },

  applyEdgeUpsert: (edge: EdgeResponse) => {
    const { nodes, edges, expanded, rootNodeId, hoveredNodeId } = get()
    const newEdges = new Map(edges)
    newEdges.set(edge.id, edge)
    set({
      edges: newEdges,
      flowEdges: computeFlowEdges(newEdges, nodes, expanded, rootNodeId, hoveredNodeId),
    })
  },

  applyEdgeRemove: (id: string) => {
    const { nodes, edges, expanded, rootNodeId, hoveredNodeId } = get()
    if (!edges.has(id)) return
    const newEdges = new Map(edges)
    newEdges.delete(id)
    set({
      edges: newEdges,
      flowEdges: computeFlowEdges(newEdges, nodes, expanded, rootNodeId, hoveredNodeId),
    })
  },

  reset: () => {
    _neighborsLoadedFor.clear()
    set(makeEmptyState())
  },
}))

// ── internal helpers ──────────────────────────────────────────────────────────

async function mergeChildren(
  nodeId: string,
  get: () => GraphState,
  set: (partial: Partial<GraphState>) => void,
): Promise<void> {
  const { get: getApi } = await import('../api/client')
  const resp = await getApi<ChildrenResponse>(`/api/graph/children/${nodeId}`)

  const { nodes, edges, expanded, positions, rootNodeId, hoveredNodeId } = get()
  const newNodes = new Map(nodes)
  const newEdges = new Map(edges)
  resp.nodes.forEach((n) => newNodes.set(n.id, n))
  resp.edges.forEach((e) => newEdges.set(e.id, e))

  // If this node is already considered expanded, the new children must get
  // positions immediately (otherwise they stack at (0,0)). expand() will do
  // its own gridLayoutAll, so this only matters on the restore path.
  const newPositions = new Map(positions)
  if (expanded.has(nodeId)) {
    placeUnpositionedChildren(nodeId, newNodes, newPositions)
  }

  set({
    nodes: newNodes,
    edges: newEdges,
    positions: newPositions,
    flowNodes: computeFlowNodes(newNodes, expanded, newPositions, rootNodeId),
    flowEdges: computeFlowEdges(newEdges, newNodes, expanded, rootNodeId, hoveredNodeId),
  })
}

const _neighborsLoadedFor = new Set<string>()

async function loadNeighborsIfNeeded(
  nodeId: string,
  get: () => GraphState,
  set: (partial: Partial<GraphState>) => void,
): Promise<void> {
  if (_neighborsLoadedFor.has(nodeId)) return
  _neighborsLoadedFor.add(nodeId)
  try {
    const { get: getApi } = await import('../api/client')
    const resp = await getApi<ChildrenResponse>(`/api/graph/neighbors/${nodeId}`)
    const { nodes, edges, expanded, positions, rootNodeId, hoveredNodeId } = get()
    const newNodes = new Map(nodes)
    const newEdges = new Map(edges)
    resp.nodes.forEach((n) => newNodes.set(n.id, n))
    resp.edges.forEach((e) => newEdges.set(e.id, e))

    // For any neighbor whose parent is currently expanded, make sure it has
    // a position so it doesn't appear at (0,0) on top of siblings.
    const newPositions = new Map(positions)
    const dirtyParents = new Set<string>()
    resp.nodes.forEach((n) => {
      if (n.parentId && expanded.has(n.parentId)) dirtyParents.add(n.parentId)
    })
    dirtyParents.forEach((pid) => placeUnpositionedChildren(pid, newNodes, newPositions))

    set({
      nodes: newNodes,
      edges: newEdges,
      positions: newPositions,
      flowNodes: computeFlowNodes(newNodes, expanded, newPositions, rootNodeId),
      flowEdges: computeFlowEdges(newEdges, newNodes, expanded, rootNodeId, hoveredNodeId),
    })
  } catch {
    _neighborsLoadedFor.delete(nodeId)
  }
}
