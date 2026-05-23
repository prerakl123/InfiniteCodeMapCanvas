import {useEffect, useRef, useState} from 'react'
import {useProjectStore} from '../store/project'
import {useGraphStore} from '../store/graph'
import {get} from '../api/client'
import type {BrowseResponse} from '../api/types'

const LS_KEY = 'lastProjectPath'

interface ProjectPickerProps {
  onClose: () => void
}

// ── DirBrowser ────────────────────────────────────────────────────────────────

interface DirBrowserProps {
  onSelect: (path: string) => void
  initialPath: string
}

function DirBrowser({ onSelect, initialPath }: DirBrowserProps) {
  const [browse, setBrowse] = useState<BrowseResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const navigate = async (path: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await get<BrowseResponse>(`/api/fs/browse?path=${encodeURIComponent(path)}`)
      setBrowse(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void navigate(initialPath || '~')
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  const dirs = browse?.entries.filter((e) => e.isDir) ?? []

  return (
    <div className="dir-browser">
      <div className="dir-browser-bar">
        {browse?.parent && (
          <button
            className="dir-browser-up"
            onClick={() => void navigate(browse.parent!)}
            title="Go up"
          >
            ↑ ..
          </button>
        )}
        <span className="dir-browser-cwd" title={browse?.path ?? ''}>
          {browse?.path ?? ''}
        </span>
        <button
          className="dir-browser-select"
          onClick={() => browse && onSelect(browse.path)}
          disabled={!browse}
        >
          Select
        </button>
      </div>

      {loading && <p className="dir-browser-msg">Loading…</p>}
      {error && <p className="dir-browser-msg dir-browser-error">{error}</p>}

      {!loading && browse && (
        <ul className="dir-browser-list">
          {dirs.length === 0 && (
            <li className="dir-browser-empty">No subdirectories</li>
          )}
          {dirs.map((entry) => (
            <li key={entry.path}>
              <button
                className="dir-browser-entry"
                onClick={() => void navigate(entry.path)}
              >
                <span className="dir-browser-icon">📁</span>
                {entry.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── ProjectPicker ─────────────────────────────────────────────────────────────

export default function ProjectPicker({ onClose }: ProjectPickerProps) {
  const [path, setPath] = useState<string>(() => localStorage.getItem(LS_KEY) ?? '')
  const [showBrowser, setShowBrowser] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)

  const status = useProjectStore((s) => s.status)
  const storeError = useProjectStore((s) => s.error)
  const indexingFraction = useProjectStore((s) => s.indexingFraction)
  const indexingCurrent = useProjectStore((s) => s.indexingCurrent)
  const projectId = useProjectStore((s) => s.projectId)
  const openProject = useProjectStore((s) => s.openProject)
  const loadRoot = useGraphStore((s) => s.loadRoot)
  const resetGraph = useGraphStore((s) => s.reset)

  const inputRef = useRef<HTMLInputElement>(null)
  const submittedRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Only auto-close when status reaches 'ready' after the user actually submitted
  useEffect(() => {
    if (submittedRef.current && status === 'ready' && projectId) {
      void loadRoot(projectId).then(() => onClose())
    }
  }, [status, projectId, loadRoot, onClose])

  const handleOpen = async () => {
    const trimmed = path.trim()
    if (!trimmed) {
      setLocalError('Please enter or browse to a project directory.')
      return
    }
    setLocalError(null)
    localStorage.setItem(LS_KEY, trimmed)
    submittedRef.current = true
    resetGraph()
    await openProject(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') void handleOpen()
  }

  const handleBrowserSelect = (selected: string) => {
    setPath(selected)
    setShowBrowser(false)
    inputRef.current?.focus()
  }

  const isOpening = status === 'opening' || status === 'indexing'
  const displayError = localError ?? (status === 'error' ? storeError : null)

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Open project">
      <div className="modal-box project-picker">
        <h2 className="modal-title">Open Project</h2>
        <p className="modal-subtitle">Select or enter the path to your Python project directory.</p>

        <div className="picker-input-row">
          <input
            ref={inputRef}
            className="picker-input"
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="/home/user/myproject"
            disabled={isOpening}
            aria-label="Project path"
          />
          <button
            className="picker-browse-btn"
            onClick={() => setShowBrowser((v) => !v)}
            disabled={isOpening}
            title="Browse filesystem"
          >
            Browse
          </button>
          <button
            className="picker-open-btn"
            onClick={() => void handleOpen()}
            disabled={isOpening || !path.trim()}
          >
            {isOpening ? 'Opening…' : 'Open'}
          </button>
        </div>

        {showBrowser && !isOpening && (
          <DirBrowser onSelect={handleBrowserSelect} initialPath={path || '~'} />
        )}

        {status === 'indexing' && (
          <div className="indexing-status">
            <div className="progress-bar">
              <div
                className="progress-fill"
                style={{ width: `${Math.round(indexingFraction * 100)}%` }}
              />
            </div>
            <span className="indexing-label">
              {Math.round(indexingFraction * 100)}% — {indexingCurrent || 'Indexing…'}
            </span>
          </div>
        )}

        {displayError && (
          <p className="picker-error" role="alert">
            {displayError}
          </p>
        )}
      </div>
    </div>
  )
}
