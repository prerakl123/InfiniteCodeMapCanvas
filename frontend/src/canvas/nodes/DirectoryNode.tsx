import {memo} from 'react'
import type {NodeProps} from '@xyflow/react'
import {Handle, Position} from '@xyflow/react'
import type {NodeResponse} from '../../api/types'
import {useGraphStore} from '../../store/graph'

interface DirectoryNodeData {
  node: NodeResponse
  isExpanded: boolean
  hasChildren: boolean
  [key: string]: unknown
}

function DirectoryNode({ data }: NodeProps) {
  const { node, isExpanded } = data as DirectoryNodeData
  const expand = useGraphStore((s) => s.expand)
  const collapse = useGraphStore((s) => s.collapse)

  const childCounts = node.meta.child_counts as Record<string, number> | undefined
  let statsLine = ''
  if (childCounts) {
    const parts: string[] = []
    if (childCounts.directories) parts.push(`${childCounts.directories} dir${childCounts.directories !== 1 ? 's' : ''}`)
    if (childCounts.files) parts.push(`${childCounts.files} file${childCounts.files !== 1 ? 's' : ''}`)
    statsLine = parts.join(', ')
  }

  const handleToggle = () => {
    if (isExpanded) {
      collapse(node.id)
    } else {
      void expand(node.id)
    }
  }

  return (
    <div className="dir-node">
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className="node-icon" aria-hidden="true">📁</span>
        <span className="node-name">{node.name}</span>
        <button
          className="node-toggle"
          onClick={handleToggle}
          title={isExpanded ? 'Collapse' : 'Expand'}
          aria-label={isExpanded ? 'Collapse directory' : 'Expand directory'}
        >
          {isExpanded ? '−' : '+'}
        </button>
      </div>
      {statsLine && <div className="node-stats">{statsLine}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(DirectoryNode)
