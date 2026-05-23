import {useEffect, useRef, useState} from 'react'
import {useProjectStore} from '../store/project'

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

  const projectStatus = useProjectStore((s) => s.status)
  const hasProject = projectStatus === 'ready' || projectStatus === 'indexing'

  useEffect(() => {
    let cancelled = false

    fetch('/api/health')
      .then((r) => r.json())
      .then((d: { status: string; version: string }) => {
        if (!cancelled) setHealth(`${d.status} · v${d.version}`)
      })
      .catch(() => {
        if (!cancelled) setHealth('unreachable')
      })

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/echo`)
    wsRef.current = ws

    ws.addEventListener('open', () => setWsStatus('open'))
    ws.addEventListener('close', () => setWsStatus('closed'))
    ws.addEventListener('error', () => setWsStatus('closed'))
    ws.addEventListener('message', (event) => {
      try {
        const msg = JSON.parse(event.data as string) as { type: string; message?: string }
        setLastEcho(`${msg.type}: ${msg.message ?? ''}`)
      } catch {
        setLastEcho(`raw: ${String(event.data)}`)
      }
    })

    return () => {
      cancelled = true
      ws.close()
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

      <span className={`badge badge-${wsStatus}`}>ws: {wsStatus}</span>
      <span className="badge">api: {health}</span>

      {/* Diagnostic WS echo — kept for smoke tests (T-0.6) */}
      <button onClick={sendPing} disabled={wsStatus !== 'open'} className="top-bar-btn top-bar-btn--sm">
        ping
      </button>
      <span className="echo">last: {lastEcho}</span>
    </header>
  )
}