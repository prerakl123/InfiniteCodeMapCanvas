import {memo} from 'react'
import type {NodeProps} from '@xyflow/react'
import {Handle, Position} from '@xyflow/react'
import type {NodeResponse} from '../../api/types'
import {useGraphStore} from '../../store/graph'

interface FileNodeData {
  node: NodeResponse
  isExpanded: boolean
  hasChildren: boolean
  isCompound: boolean
  [key: string]: unknown
}

function FileNode({ data }: NodeProps) {
  const { node, isExpanded, hasChildren, isCompound } = data as FileNodeData
  const expand = useGraphStore((s) => s.expand)
  const collapse = useGraphStore((s) => s.collapse)

  const loc = typeof node.meta.loc === 'number' ? node.meta.loc : null
  const classCount = typeof node.meta.class_count === 'number' ? node.meta.class_count : 0
  const fnCount = typeof node.meta.function_count === 'number' ? node.meta.function_count : 0
  const parseError = typeof node.meta.parse_error === 'string' ? node.meta.parse_error : null

  const statsParts: string[] = []
  if (loc !== null && loc > 0) statsParts.push(`${loc} LOC`)
  if (classCount) statsParts.push(`${classCount} class${classCount !== 1 ? 'es' : ''}`)
  if (fnCount) statsParts.push(`${fnCount} fn${fnCount !== 1 ? 's' : ''}`)
  const statsLine = statsParts.join(' · ')

  const handleToggle = () => {
    if (isExpanded) {
      collapse(node.id)
    } else {
      void expand(node.id)
    }
  }

  const classes = ['file-node']
  if (parseError) classes.push('file-node--error')
  if (isCompound) classes.push('node--compound')

  return (
    <div className={classes.join(' ')} title={parseError ?? undefined}>
      <Handle type="target" position={Position.Left} />
      <div className="node-header">
        <span className="node-icon" aria-hidden="true">{parseError ? '⚠️' : '📄'}</span>
        <span className="node-name">{node.name}</span>
        <button
          className="node-toggle"
          onClick={handleToggle}
          disabled={!hasChildren && classCount + fnCount === 0}
          title={hasChildren ? (isExpanded ? 'Collapse' : 'Expand') : 'No children'}
          aria-label={isExpanded ? 'Collapse file' : 'Expand file'}
        >
          {isExpanded ? '−' : '+'}
        </button>
      </div>
      {parseError && <div className="node-stats node-error">parse error</div>}
      {statsLine && <div className="node-stats">{statsLine}</div>}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default memo(FileNode)
