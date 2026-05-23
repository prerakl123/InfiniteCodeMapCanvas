import {useEffect, useRef, useState} from 'react'
import {useProjectStore} from '../store/project'
import {useGraphStore} from '../store/graph'
import {EDGE_KIND_COLORS} from '../canvas/edges/edgeStyles'

interface MenuBarProps {
  onOpenProject: () => void
  onShowStats: () => void
}

type WsStatus = 'connecting' | 'open' | 'closed'

export default function MenuBar({ onOpenProject, onShowStats }: MenuBarProps) {
  const [wsStatus, setWsStatus] = useState<WsStatus>('connecting')
  const [health, setHealth] = useState<string>('checking…')
  const [lastEcho, setLastEcho] = useState<string>('—')
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<number | null>(null)
  const cancelledRef = useRef(false)

  const projectStatus = useProjectStore((s) => s.status)
  const hasProject = projectStatus === 'ready' || projectStatus === 'indexing'
  const tidy = useGraphStore((s) => s.tidy)
  const resetGraph = useGraphStore((s) => s.reset)
  const forceReindex = useProjectStore((s) => s.forceReindex)

  const handleForceReindex = async () => {
    const confirmed = window.confirm(
      'Force re-index will wipe the cached index for this project and rebuild it from scratch. Continue?',
    )
    if (!confirmed) return
    resetGraph()
    await forceReindex()
  }

  useEffect(() => {
    cancelledRef.current = false

    fetch('/api/health')
      .then((r) => r.json())
      .then((d: { status: string; version: string }) => {
        if (!cancelledRef.current) setHealth(`${d.status} · v${d.version}`)
      })
      .catch(() => {
        if (!cancelledRef.current) setHealth('unreachable')
      })

    const connect = () => {
      if (cancelledRef.current) return
      setWsStatus('connecting')
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${window.location.host}/ws/echo`)
      wsRef.current = ws

      ws.addEventListener('open', () => setWsStatus('open'))
      ws.addEventListener('close', () => {
        setWsStatus('closed')
        if (cancelledRef.current) return
        // Reconnect with a fixed 2s backoff. The echo socket is purely a
        // diagnostic; we don't need exponential backoff.
        retryRef.current = window.setTimeout(connect, 2000)
      })
      ws.addEventListener('error', () => {
        // close handler will fire and trigger reconnect
      })
      ws.addEventListener('message', (event) => {
        try {
          const msg = JSON.parse(event.data as string) as { type: string; message?: string }
          setLastEcho(`${msg.type}: ${msg.message ?? ''}`)
        } catch {
          setLastEcho(`raw: ${String(event.data)}`)
        }
      })
    }

    connect()

    return () => {
      cancelledRef.current = true
      if (retryRef.current !== null) {
        window.clearTimeout(retryRef.current)
        retryRef.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [])

  const sendPing = () => {
    const stamp = new Date().toISOString().split('T')[1]?.replace('Z', '') ?? ''
    wsRef.current?.send(`ping ${stamp}`)
  }

  return (
    <header className="top-bar">
      <strong className="title">InfiniteCodeMapCanvas</strong>

      <button className="top-bar-btn" onClick={onOpenProject}>
        Open Project
      </button>

      <button className="top-bar-btn" onClick={onShowStats} disabled={!hasProject}>
        Stats
      </button>

      <button
        className="top-bar-btn"
        onClick={() => tidy()}
        disabled={!hasProject}
        title="Re-grid every expanded compound. Multi-layout (tree / circular / force) is Phase 5."
      >
        Tidy
      </button>

      <button
        className="top-bar-btn"
        onClick={() => void handleForceReindex()}
        disabled={!hasProject}
        title="Wipe the cached index for this project and rebuild from scratch"
      >
        Force Reindex
      </button>

      <span className={`badge badge-${wsStatus}`}>ws: {wsStatus}</span>
      <span className="badge">api: {health}</span>

      <span className="edge-legend">
        {Object.entries(EDGE_KIND_COLORS).map(([kind, color]) => (
          <span key={kind} className="edge-legend-item" style={{ color }}>
            <span className="edge-legend-swatch" /> {kind}
          </span>
        ))}
      </span>

      {/* Diagnostic WS echo — kept for smoke tests (T-0.6) */}
      <button onClick={sendPing} disabled={wsStatus !== 'open'} className="top-bar-btn top-bar-btn--sm">
        ping
      </button>
      <span className="echo">last: {lastEcho}</span>
    </header>
  )
}
