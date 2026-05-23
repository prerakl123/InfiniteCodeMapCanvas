import {memo} from 'react'
import type {NodeProps} from '@xyflow/react'
import {Handle, Position} from '@xyflow/react'
import type {NodeResponse} from '../../api/types'
import {useGraphStore} from '../../store/graph'

interface ClassNodeData {
  node: NodeResponse
  isExpanded: boolean
  hasChildren: boolean
  isCompound: boolean
  [key: string]: unknown
}

function ClassNode({ data }: NodeProps) {
  const { node, isExpanded, hasChildren, isCompound } = data as ClassNodeData
  const expand = useGraphStore((s) => s.expand)
  const collapse = useGraphStore((s) => s.collapse)

  const meta = node.meta as Record<string, unknown>
  const methodCount = typeof meta.method_count === 'number' ? meta.method_count : 0
  const bases = Array.isArray(meta.bases) ? (meta.bases as string[]) : []
  const decorators = Array.isArray(meta.decorators) ? (meta.decorators as string[]) : []

  const statsLine = [
    methodCount ? `${methodCount} method${methodCount !== 1 ? 's' : ''}` : '',
    bases.length ? `← ${bases.join(', ')}` : '',
  ].filter(Boolean).join(' · ')

  const docExcerpt = typeof meta.docstring_excerpt === 'string' ? meta.docstring_excerpt : ''

  const handleToggle = () => {
    if (isExpanded) collapse(node.id)
    else void expand(node.id)
  }

  return (
    <div className={isCompound ? 'class-node node--compound' : 'class-node'} title={docExcerpt || undefined}>
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className="node-icon" aria-hidden="true">🏛</span>
        <span className="node-name">{node.name}</span>
        {decorators.length > 0 && (
          <span className="node-badge" title={`@${decorators.join(', @')}`}>@</span>
        )}
        <button
          className="node-toggle"
          onClick={handleToggle}
          disabled={!hasChildren && methodCount === 0}
          title={hasChildren ? (isExpanded ? 'Collapse' : 'Expand') : 'No children'}
          aria-label={isExpanded ? 'Collapse class' : 'Expand class'}
        >
          {isExpanded ? '−' : '+'}
        </button>
      </div>
      {statsLine && <div className="node-stats">{statsLine}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(ClassNode)
