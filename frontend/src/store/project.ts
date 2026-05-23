import {create} from 'zustand'
import {get, post} from '../api/client'
import type {IndexingStatus, OpenProjectResponse} from '../api/types'
import {type ProjectEvent, ProjectEventClient} from '../api/ws'
import {useGraphStore} from './graph'

let _wsClient: ProjectEventClient | null = null

interface ProjectState {
  projectId: string | null
  projectRoot: string | null
  codemapDir: string | null
  status: 'idle' | 'opening' | 'indexing' | 'ready' | 'error'
  indexingFraction: number
  indexingCurrent: string
  error: string | null
  // True when the last error was flagged by the server as recoverable via
  // a force reset (e.g. schema mismatch). The picker uses this to surface
  // a "Force re-index" button.
  recoverable: boolean

  openProject: (path: string, force?: boolean) => Promise<void>
  forceReindex: () => Promise<void>
  pollIndexing: () => Promise<void>
  setReady: () => void
  subscribeEvents: () => void
}

export const useProjectStore = create<ProjectState>((set, get_) => ({
  projectId: null,
  projectRoot: null,
  codemapDir: null,
  status: 'idle',
  indexingFraction: 0,
  indexingCurrent: '',
  error: null,
  recoverable: false,

  openProject: async (path: string, force = false) => {
    set({
      status: 'opening',
      error: null,
      recoverable: false,
      indexingFraction: 0,
      indexingCurrent: '',
    })
    try {
      const resp = await post<OpenProjectResponse>('/api/project', { path, force })
      set({
        projectId: resp.project_id,
        projectRoot: path,
        codemapDir: resp.codemap_dir,
        status: 'indexing',
      })
      get_().subscribeEvents()
      await get_().pollIndexing()
    } catch (err) {
      const parsed = parseApiError(err)
      set({
        status: 'error',
        error: parsed.message,
        recoverable: parsed.recoverable,
      })
    }
  },

  forceReindex: async () => {
    const projectId = get_().projectId
    const projectRoot = get_().projectRoot
    if (!projectId || !projectRoot) return
    set({
      status: 'opening',
      error: null,
      recoverable: false,
      indexingFraction: 0,
      indexingCurrent: '',
    })
    try {
      await post(`/api/project/${projectId}/reindex?force=true`)
      set({ status: 'indexing' })
      // Re-subscribe: the underlying store/session was closed and reopened.
      get_().subscribeEvents()
      await get_().pollIndexing()
    } catch (err) {
      const parsed = parseApiError(err)
      set({
        status: 'error',
        error: parsed.message,
        recoverable: parsed.recoverable,
      })
    }
  },

  pollIndexing: async () => {
    const projectId = get_().projectId
    if (!projectId) return

    const poll = async (): Promise<void> => {
      try {
        const status = await get<IndexingStatus>(`/api/project/${projectId}/status`)
        set({ indexingFraction: status.fraction, indexingCurrent: status.current })
        if (status.error) {
          set({ status: 'error', error: status.error })
          return
        }
        if (status.done) {
          set({ status: 'ready' })
          return
        }
        await new Promise<void>((resolve) => setTimeout(resolve, 500))
        return poll()
      } catch (err) {
        set({ status: 'error', error: err instanceof Error ? err.message : String(err) })
      }
    }

    await poll()
  },

  setReady: () => set({ status: 'ready' }),

  subscribeEvents: () => {
    const projectId = get_().projectId
    if (!projectId) return
    if (_wsClient) {
      _wsClient.close()
    }
    _wsClient = new ProjectEventClient(projectId, {
      onEvent: (evt: ProjectEvent) => handleProjectEvent(set, evt),
    })
    _wsClient.connect()
  },
}))

interface ParsedApiError {
  message: string
  recoverable: boolean
}

// Backend may return HTTPException(detail=...) where detail is either a
// plain string or a structured object like
//   {message, recoverable: true, action: 'force_reset'}.
// `api/client.ts` re-throws the raw response body as Error.message, so we
// try to parse JSON out of it here.
function parseApiError(err: unknown): ParsedApiError {
  const raw = err instanceof Error ? err.message : String(err)
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown }
    const detail = parsed.detail
    if (detail && typeof detail === 'object') {
      const d = detail as { message?: string; recoverable?: boolean }
      return {
        message: typeof d.message === 'string' ? d.message : raw,
        recoverable: d.recoverable === true,
      }
    }
    if (typeof detail === 'string') {
      return { message: detail, recoverable: false }
    }
  } catch {
    // not JSON
  }
  return { message: raw, recoverable: false }
}

function handleProjectEvent(
  set: (partial: Partial<ProjectState>) => void,
  evt: ProjectEvent,
): void {
  const graph = useGraphStore.getState()
  switch (evt.type) {
    case 'node.added':
    case 'node.changed':
      graph.applyNodeUpsert(evt.node)
      break
    case 'node.removed':
      graph.applyNodeRemove(evt.id)
      break
    case 'edge.added':
      graph.applyEdgeUpsert(evt.edge)
      break
    case 'edge.removed':
      graph.applyEdgeRemove(evt.id)
      break
    case 'indexing.progress':
      set({ indexingFraction: evt.fraction, indexingCurrent: evt.current })
      break
    case 'indexing.complete':
      set({ status: 'ready', indexingFraction: 1 })
      break
    case 'indexing.error':
      set({ status: 'error', error: evt.error })
      break
    case 'resync_required':
      // Could trigger a refetch of the root tree; left as a future improvement.
      break
  }
}
