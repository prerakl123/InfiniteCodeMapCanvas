import {memo} from 'react'
import type {NodeProps} from '@xyflow/react'
import {Handle, Position} from '@xyflow/react'
import type {NodeResponse} from '../../api/types'

interface ExternalNodeData {
  node: NodeResponse
  isExpanded: boolean
  hasChildren: boolean
  [key: string]: unknown
}

function ExternalModuleNode({ data }: NodeProps) {
  const { node } = data as ExternalNodeData
  const meta = node.meta as Record<string, unknown>
  const topLevel = typeof meta.top_level === 'string' ? meta.top_level : node.name

  return (
    <div className="external-node" title={`external: ${topLevel}`}>
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className="node-icon" aria-hidden="true">📦</span>
        <span className="node-name">{node.name}</span>
      </div>
      <div className="node-stats">external</div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(ExternalModuleNode)
