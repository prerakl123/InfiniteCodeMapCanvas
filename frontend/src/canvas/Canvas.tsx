import {useCallback, useRef} from 'react'
import {
  Background,
  Controls,
  MiniMap,
  type NodeChange,
  type NodeMouseHandler,
  type NodeTypes,
  type OnNodeDrag,
  PanOnScrollMode,
  ReactFlow,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {useGraphStore} from '../store/graph'
import DirectoryNode from './nodes/DirectoryNode'
import FileNode from './nodes/FileNode'
import ClassNode from './nodes/ClassNode'
import FunctionNode from './nodes/FunctionNode'
import ExternalModuleNode from './nodes/ExternalModuleNode'

const nodeTypes: NodeTypes = {
  directory: DirectoryNode,
  file: FileNode,
  class: ClassNode,
  function: FunctionNode,
  external: ExternalModuleNode,
}

// Effectively infinite zoom/pan limits. ReactFlow requires finite numbers.
const MIN_ZOOM = 0.0005
const MAX_ZOOM = 8

export default function Canvas() {
  const nodes = useGraphStore((s) => s.flowNodes)
  const edges = useGraphStore((s) => s.flowEdges)
  const setNodePosition = useGraphStore((s) => s.setNodePosition)
  const setHoveredNode = useGraphStore((s) => s.setHoveredNode)

  // Debounce hover so rapid mouse moves don't thrash the highlight CSS class
  // and re-render every edge each pointer pixel.
  const hoverTimer = useRef<number | null>(null)
  const pendingHover = useRef<string | null>(null)
  const scheduleHover = useCallback(
    (id: string | null) => {
      pendingHover.current = id
      if (hoverTimer.current !== null) return
      hoverTimer.current = window.setTimeout(() => {
        hoverTimer.current = null
        setHoveredNode(pendingHover.current)
      }, 80)
    },
    [setHoveredNode],
  )

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      for (const ch of changes) {
        if (ch.type === 'position' && ch.position) {
          const isDragging = ch.dragging === true
          setNodePosition(ch.id, ch.position, !isDragging)
        }
      }
    },
    [setNodePosition],
  )

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_event, node) => {
      setNodePosition(node.id, node.position, true)
    },
    [setNodePosition],
  )

  const onNodeMouseEnter: NodeMouseHandler = useCallback(
    (_event, node) => scheduleHover(node.id),
    [scheduleHover],
  )

  const onNodeMouseLeave: NodeMouseHandler = useCallback(
    () => scheduleHover(null),
    [scheduleHover],
  )

  const onConnect = useCallback(() => {
    // no-op
  }, [])

  // Suppress browser context menu so right-click can drive canvas pan.
  const onContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
  }, [])

  return (
    <div style={{ width: '100%', height: '100%' }} onContextMenu={onContextMenu}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={onNodeDragStop}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        onConnect={onConnect}
        fitView
        fitViewOptions={{ padding: 0.3, minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM }}
        minZoom={MIN_ZOOM}
        maxZoom={MAX_ZOOM}
        // ── interaction model ──
        // Plain scroll pans. Ctrl+scroll zooms. Touchpad pinch zooms.
        panOnScroll
        panOnScrollMode={PanOnScrollMode.Free}
        zoomOnScroll={false}
        zoomOnPinch
        zoomOnDoubleClick={false}
        zoomActivationKeyCode="Control"
        // Right-mouse-button only for canvas pan; left/middle reserved.
        panOnDrag={[2]}
        selectionOnDrag={false}
        // Left-click selects (highlight); left-click+hold drags a node.
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
      >
        <Background gap={24} color="#1f2937" />
        <MiniMap pannable zoomable maskColor="rgba(0,0,0,0.6)" />
        <Controls />
      </ReactFlow>
    </div>
  )
}
