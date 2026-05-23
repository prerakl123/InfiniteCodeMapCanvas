import {memo} from 'react'
import type {NodeProps} from '@xyflow/react'
import {Handle, Position} from '@xyflow/react'
import type {NodeResponse} from '../../api/types'

interface FunctionNodeData {
  node: NodeResponse
  isExpanded: boolean
  hasChildren: boolean
  [key: string]: unknown
}

function FunctionNode({ data }: NodeProps) {
  const { node } = data as FunctionNodeData
  const meta = node.meta as Record<string, unknown>
  const isAsync = meta.is_async === true
  const isGenerator = meta.is_generator === true
  const paramCount = typeof meta.param_count === 'number' ? meta.param_count : 0
  const decorators = Array.isArray(meta.decorators) ? (meta.decorators as string[]) : []
  const callsOut = typeof meta.calls_out_count === 'number' ? meta.calls_out_count : 0
  const docExcerpt = typeof meta.docstring_excerpt === 'string' ? meta.docstring_excerpt : ''

  const isMethod = node.kind === 'method'
  const icon = isMethod ? 'ƒ' : 'ƒ'
  const flairs: string[] = []
  if (isAsync) flairs.push('async')
  if (isGenerator) flairs.push('gen')

  const statsParts = [
    flairs.length ? flairs.join(' ') : '',
    paramCount ? `${paramCount} param${paramCount !== 1 ? 's' : ''}` : '',
    callsOut ? `${callsOut} calls` : '',
  ].filter(Boolean)

  return (
    <div className={isMethod ? 'method-node' : 'function-node'} title={docExcerpt || undefined}>
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className="node-icon" aria-hidden="true">{icon}</span>
        <span className="node-name">{node.name}</span>
        {decorators.length > 0 && (
          <span className="node-badge" title={`@${decorators.join(', @')}`}>@</span>
        )}
      </div>
      {statsParts.length > 0 && <div className="node-stats">{statsParts.join(' · ')}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(FunctionNode)
