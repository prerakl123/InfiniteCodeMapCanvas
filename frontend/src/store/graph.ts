import {create} from 'zustand'
import type {Edge, Node} from '@xyflow/react'
import type {ChildrenResponse, EdgeResponse, NodeResponse} from '../api/types'

const NODE_WIDTH = 220
const NODE_HEIGHT = 72
const GRID_GAP_X = 60
const GRID_GAP_Y = 40

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

// ── pure computation helpers ──────────────────────────────────────────────────

function autoLayoutChildren(
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
        x: (idx % cols) * (NODE_WIDTH + GRID_GAP_X) + 16,
        y: Math.floor(idx / cols) * (NODE_HEIGHT + GRID_GAP_Y) + 48,
      })
    }
  })
}

function computeFlowNodes(
  nodes: Map<string, NodeResponse>,
  expanded: Set<string>,
  positions: Map<string, { x: number; y: number }>,
  rootNodeId: string | null,
): Node[] {
  // Count loaded children per expanded node to size compound parents
  const loadedChildCount = new Map<string, number>()
  nodes.forEach((node) => {
    if (node.parentId && expanded.has(node.parentId)) {
      loadedChildCount.set(node.parentId, (loadedChildCount.get(node.parentId) ?? 0) + 1)
    }
  })

  const result: Node[] = []
  nodes.forEach((node) => {
    const isRoot = node.id === rootNodeId
    const isVisible = isRoot || (node.parentId !== null && expanded.has(node.parentId))
    if (!isVisible) return

    const pos = positions.get(node.id) ?? { x: 0, y: 0 }
    const isExpanded = expanded.has(node.id)
    const childCount = loadedChildCount.get(node.id) ?? 0
    const hasChildren = childCount > 0

    const flowNode: Node = {
      id: node.id,
      position: pos,
      data: { node, isExpanded, hasChildren },
      type: node.kind === 'directory' ? 'directory' : node.kind === 'file' ? 'file' : 'default',
    }

    // Compound node: size the expanded parent to contain its children
    if (isExpanded && childCount > 0) {
      const cols = Math.ceil(Math.sqrt(childCount))
      const rows = Math.ceil(childCount / cols)
      flowNode.style = {
        width: Math.max(NODE_WIDTH + 32, cols * (NODE_WIDTH + GRID_GAP_X) + 32),
        height: 88 + rows * (NODE_HEIGHT + GRID_GAP_Y),
      }
    }

    if (!isRoot && node.parentId && expanded.has(node.parentId)) {
      flowNode.parentId = node.parentId
      flowNode.extent = 'parent'
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

  const result: Edge[] = []
  const seen = new Set<string>()
  edges.forEach((edge) => {
    const src = resolveEndpoint(edge.sourceId)
    const tgt = resolveEndpoint(edge.targetId)
    if (!src || !tgt || src === tgt) return
    const dedupKey = `${src}::${tgt}::${edge.kind}`
    if (seen.has(dedupKey)) return
    seen.add(dedupKey)
    result.push({
      id: edge.id,
      source: src,
      target: tgt,
      label: edge.kind,
      animated: edge.kind === 'imports',
      data: { edge },
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

  // Cached ReactFlow arrays — subscribe to these in components, not computed fns
  flowNodes: Node[]
  flowEdges: Edge[]

  loadRoot: (projectId: string) => Promise<void>
  expand: (nodeId: string) => Promise<void>
  collapse: (nodeId: string) => void
  setNodePosition: (nodeId: string, position: { x: number; y: number }) => void
  reset: () => void
}

const emptyState = {
  nodes: new Map<string, NodeResponse>(),
  edges: new Map<string, EdgeResponse>(),
  expanded: new Set<string>(),
  userPositioned: new Set<string>(),
  positions: new Map<string, { x: number; y: number }>(),
  rootNodeId: null as string | null,
  flowNodes: [] as Node[],
  flowEdges: [] as Edge[],
}

export const useGraphStore = create<GraphState>((set, get) => ({
  ...emptyState,

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
      flowNodes: computeFlowNodes(nodes, expanded, positions, root.id),
      flowEdges: computeFlowEdges(edges, nodes, expanded, root.id),
    })

    if (saved && saved.expanded.length > 0) {
      for (const nodeId of saved.expanded) {
        try {
          await mergeChildren(nodeId, get, set)
        } catch {
          // ignore — node may no longer exist after reindex
        }
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
    autoLayoutChildren(nodeId, get().nodes, newPositions, newUserPositioned)

    const { nodes, edges } = get()
    set({
      expanded: newExpanded,
      positions: newPositions,
      flowNodes: computeFlowNodes(nodes, newExpanded, newPositions, rootNodeId),
      flowEdges: computeFlowEdges(edges, nodes, newExpanded, rootNodeId),
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

    set({
      expanded: newExpanded,
      flowNodes: computeFlowNodes(nodes, newExpanded, positions, rootNodeId),
      flowEdges: computeFlowEdges(edges, nodes, newExpanded, rootNodeId),
    })

    if (rootNodeId) saveToStorage(rootNodeId, newExpanded, positions)
  },

  setNodePosition: (nodeId: string, position: { x: number; y: number }) => {
    const { userPositioned, positions, rootNodeId, expanded, nodes } = get()
    const newPositions = new Map(positions)
    newPositions.set(nodeId, position)
    const newUserPositioned = new Set(userPositioned)
    newUserPositioned.add(nodeId)

    set({
      positions: newPositions,
      userPositioned: newUserPositioned,
      flowNodes: computeFlowNodes(nodes, expanded, newPositions, rootNodeId),
    })

    if (rootNodeId) saveToStorage(rootNodeId, expanded, newPositions)
  },

  reset: () => set({ ...emptyState }),
}))

// ── internal helper ───────────────────────────────────────────────────────────

async function mergeChildren(
  nodeId: string,
  get: () => GraphState,
  set: (partial: Partial<GraphState>) => void,
): Promise<void> {
  const { get: getApi } = await import('../api/client')
  const resp = await getApi<ChildrenResponse>(`/api/graph/children/${nodeId}`)

  const { nodes, edges, expanded, positions, rootNodeId } = get()
  const newNodes = new Map(nodes)
  const newEdges = new Map(edges)
  resp.nodes.forEach((n) => newNodes.set(n.id, n))
  resp.edges.forEach((e) => newEdges.set(e.id, e))

  set({
    nodes: newNodes,
    edges: newEdges,
    flowNodes: computeFlowNodes(newNodes, expanded, positions, rootNodeId),
    flowEdges: computeFlowEdges(newEdges, newNodes, expanded, rootNodeId),
  })
}
