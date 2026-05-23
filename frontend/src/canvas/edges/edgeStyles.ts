import type {EdgeResponse} from '../../api/types'
import type {Edge} from '@xyflow/react'

// Colour-blind-safe palette (Wong / Okabe-Ito-derived).
const KIND_COLORS: Record<string, string> = {
  imports: '#3b82f6',
  inherits: '#a855f7',
  instantiates: '#14b8a6',
  calls: '#f59e0b',
  decorates: '#94a3b8',
}

// Priority order when picking a representative colour for a bundled edge:
// inherits > instantiates > imports > calls > decorates. Inherits/instantiates
// are usually more semantically interesting than calls in a dense graph.
const KIND_PRIORITY = ['inherits', 'instantiates', 'imports', 'calls', 'decorates']

type StyledEdge = Pick<Edge, 'style' | 'animated' | 'label' | 'labelStyle'>

export function styleEdge(edge: EdgeResponse): StyledEdge {
  const color = KIND_COLORS[edge.kind] ?? '#475569'
  const lowConf = edge.confidence < 0.99
  return {
    style: {
      stroke: color,
      strokeWidth: lowConf ? 1.25 : 1.5,
      strokeDasharray: lowConf ? '6 4' : undefined,
      opacity: lowConf ? 0.55 : 0.7,
    },
    animated: false,
    // Labels are visually noisy at scale; omit by default. Hover highlight
    // already conveys "what touches this node".
  }
}

export function styleBundledEdge(kinds: Set<string>, minConfidence: number): StyledEdge {
  const repKind = KIND_PRIORITY.find((k) => kinds.has(k)) ?? Array.from(kinds)[0] ?? 'calls'
  const color = KIND_COLORS[repKind] ?? '#475569'
  const lowConf = minConfidence < 0.99
  return {
    style: {
      stroke: color,
      strokeWidth: lowConf ? 1.5 : 2,
      strokeDasharray: lowConf ? '6 4' : undefined,
      opacity: lowConf ? 0.6 : 0.8,
    },
    animated: false,
  }
}

export const EDGE_KIND_COLORS = KIND_COLORS
