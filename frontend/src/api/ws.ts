import type {EdgeResponse, NodeResponse} from './types'

export type ProjectEvent =
  | { seq: number; type: 'hello'; project_id: string; last_seq: number; indexing: { fraction: number; current: string; done: boolean; error: string | null } }
  | { seq: number; type: 'node.added'; node: NodeResponse }
  | { seq: number; type: 'node.removed'; id: string }
  | { seq: number; type: 'node.changed'; id: string; node: NodeResponse }
  | { seq: number; type: 'edge.added'; edge: EdgeResponse }
  | { seq: number; type: 'edge.removed'; id: string }
  | { seq: number; type: 'indexing.progress'; fraction: number; current: string }
  | { seq: number; type: 'indexing.complete'; node_counts: Record<string, number> }
  | { seq: number; type: 'indexing.error'; error: string }
  | { seq: number; type: 'resync_required' }
  | { seq: number; type: 'error'; error: string }

interface SubscriberOpts {
  onEvent: (evt: ProjectEvent) => void
  onClose?: () => void
}

export class ProjectEventClient {
  private ws: WebSocket | null = null
  private lastSeq: number | null = null
  private readonly projectId: string
  private readonly onEvent: (evt: ProjectEvent) => void
  private readonly onClose?: () => void
  private retryTimer: number | null = null
  private closedByUser = false

  constructor(projectId: string, opts: SubscriberOpts) {
    this.projectId = projectId
    this.onEvent = opts.onEvent
    this.onClose = opts.onClose
  }

  connect(): void {
    this.closedByUser = false
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const suffix = this.lastSeq !== null ? `?since_seq=${this.lastSeq}` : ''
    const url = `${proto}://${window.location.host}/ws/project/${this.projectId}/events${suffix}`
    this.ws = new WebSocket(url)
    this.ws.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data as string) as ProjectEvent
        if (typeof data.seq === 'number') this.lastSeq = data.seq
        this.onEvent(data)
      } catch {
        // ignore malformed frame
      }
    })
    this.ws.addEventListener('close', () => {
      if (this.closedByUser) {
        this.onClose?.()
        return
      }
      // Auto-reconnect with backoff
      this.retryTimer = window.setTimeout(() => this.connect(), 1500)
    })
    this.ws.addEventListener('error', () => {
      // close handler will deal with reconnect
    })
  }

  close(): void {
    this.closedByUser = true
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    this.ws?.close()
    this.ws = null
  }
}
