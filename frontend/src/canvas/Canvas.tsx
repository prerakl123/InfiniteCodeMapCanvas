import {useCallback} from 'react'
import {Background, Controls, MiniMap, type NodeTypes, type OnNodeDrag, ReactFlow,} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {useGraphStore} from '../store/graph'
import DirectoryNode from './nodes/DirectoryNode'
import FileNode from './nodes/FileNode'

const nodeTypes: NodeTypes = {
  directory: DirectoryNode,
  file: FileNode,
}

export default function Canvas() {
  const nodes = useGraphStore((s) => s.flowNodes)
  const edges = useGraphStore((s) => s.flowEdges)
  const setNodePosition = useGraphStore((s) => s.setNodePosition)

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_event, node) => {
      setNodePosition(node.id, node.position)
    },
    [setNodePosition],
  )

  const onConnect = useCallback(() => {
    // no-op for now
  }, [])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeDragStop={onNodeDragStop}
      onConnect={onConnect}
      fitView
      fitViewOptions={{ padding: 0.3 }}
    >
      <Background gap={24} color="#1f2937" />
      <MiniMap pannable zoomable maskColor="rgba(0,0,0,0.6)" />
      <Controls />
    </ReactFlow>
  )
}
