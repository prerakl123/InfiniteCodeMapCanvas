import {Fragment, useCallback, useEffect, useRef, useState} from 'react'
import {useProjectStore} from '../store/project'
import {get} from '../api/client'
import type {ProjectStats} from '../api/types'

interface StatsModalProps {
  onClose: () => void
}

export default function StatsModal({ onClose }: StatsModalProps) {
  const projectId = useProjectStore((s) => s.projectId)
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  const fetchStats = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError(null)
    try {
      const data = await get<ProjectStats>(`/api/project/${projectId}/stats`)
      setStats(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    void fetchStats()
    closeRef.current?.focus()
  }, [fetchStats])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Project statistics"
      onClick={handleOverlayClick}
    >
      <div className="modal-box stats-modal">
        <div className="modal-header-row">
          <h2 className="modal-title">Project Stats</h2>
          <div className="modal-header-actions">
            <button
              className="top-bar-btn"
              onClick={() => void fetchStats()}
              disabled={loading}
            >
              {loading ? 'Loading…' : 'Refresh'}
            </button>
            <button
              ref={closeRef}
              className="modal-close-btn"
              onClick={onClose}
              aria-label="Close stats"
            >
              ✕
            </button>
          </div>
        </div>

        {error && (
          <p className="picker-error" role="alert">
            {error}
          </p>
        )}

        {loading && !stats && <p className="stats-loading">Loading statistics…</p>}

        {stats && (
          <div className="stats-content">
            <section className="stats-section">
              <h3 className="stats-section-title">Runtime</h3>
              <dl className="stats-dl">
                <dt>Python</dt>
                <dd>{stats.python_version || '—'}</dd>
                <dt>Venv</dt>
                <dd>{stats.venv_path ?? 'none'}</dd>
                <dt>Package manager</dt>
                <dd>{stats.package_manager || '—'}</dd>
                <dt>Test framework</dt>
                <dd>{stats.test_framework || '—'}</dd>
              </dl>
            </section>

            <section className="stats-section">
              <h3 className="stats-section-title">Dependencies</h3>
              {stats.dependencies.length === 0 ? (
                <p className="stats-empty">No dependencies detected.</p>
              ) : (
                <ul className="stats-list">
                  {stats.dependencies.map((dep) => (
                    <li key={dep}>{dep}</li>
                  ))}
                </ul>
              )}
            </section>

            <section className="stats-section">
              <h3 className="stats-section-title">Code</h3>
              <dl className="stats-dl">
                <dt>Total LOC</dt>
                <dd>{stats.loc_total.toLocaleString()}</dd>
                {Object.entries(stats.file_counts).map(([ext, count]) => (
                  <Fragment key={ext}>
                    <dt>{ext} files</dt>
                    <dd>{count}</dd>
                  </Fragment>
                ))}
              </dl>
              {stats.entry_points.length > 0 && (
                <>
                  <h4 className="stats-subheading">Entry points</h4>
                  <ul className="stats-list">
                    {stats.entry_points.map((ep) => (
                      <li key={ep}>{ep}</li>
                    ))}
                  </ul>
                </>
              )}
            </section>

            <section className="stats-section">
              <h3 className="stats-section-title">Index Health</h3>
              <dl className="stats-dl">
                <dt>Last sync</dt>
                <dd>{stats.last_sync_at ? new Date(stats.last_sync_at).toLocaleString() : 'never'}</dd>
                <dt>Indexed files</dt>
                <dd>{stats.indexed_file_count}</dd>
                <dt>Parse errors</dt>
                <dd className={stats.parse_error_count > 0 ? 'stats-warn' : ''}>
                  {stats.parse_error_count}
                </dd>
              </dl>
              {Object.keys(stats.node_counts).length > 0 && (
                <>
                  <h4 className="stats-subheading">Node counts</h4>
                  <dl className="stats-dl">
                    {Object.entries(stats.node_counts).map(([kind, count]) => (
                      <Fragment key={kind}>
                        <dt>{kind}</dt>
                        <dd>{count}</dd>
                      </Fragment>
                    ))}
                  </dl>
                </>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
