import {memo} from 'react'
import type {NodeProps} from '@xyflow/react'
import {Handle, Position} from '@xyflow/react'
import type {NodeResponse} from '../../api/types'
import {useGraphStore} from '../../store/graph'

interface FileNodeData {
  node: NodeResponse
  isExpanded: boolean
  hasChildren: boolean
  [key: string]: unknown
}

function FileNode({ data }: NodeProps) {
  const { node, isExpanded, hasChildren } = data as FileNodeData
  const expand = useGraphStore((s) => s.expand)
  const collapse = useGraphStore((s) => s.collapse)

  const loc = typeof node.meta.loc === 'number' ? node.meta.loc : null
  const statsLine = loc !== null ? `${loc} LOC` : ''

  const handleToggle = () => {
    if (isExpanded) {
      collapse(node.id)
    } else {
      void expand(node.id)
    }
  }

  return (
    <div className="file-node">
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className="node-icon" aria-hidden="true">📄</span>
        <span className="node-name">{node.name}</span>
        <button
          className="node-toggle"
          onClick={handleToggle}
          disabled={!hasChildren}
          title={hasChildren ? (isExpanded ? 'Collapse' : 'Expand') : 'No children'}
          aria-label={isExpanded ? 'Collapse file' : 'Expand file'}
        >
          {isExpanded ? '−' : '+'}
        </button>
      </div>
      {statsLine && <div className="node-stats">{statsLine}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(FileNode)
