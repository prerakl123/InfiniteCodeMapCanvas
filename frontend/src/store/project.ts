import {create} from 'zustand'
import {get, post} from '../api/client'
import type {IndexingStatus, OpenProjectResponse} from '../api/types'

interface ProjectState {
  projectId: string | null
  projectRoot: string | null
  codemapDir: string | null
  status: 'idle' | 'opening' | 'indexing' | 'ready' | 'error'
  indexingFraction: number
  indexingCurrent: string
  error: string | null

  openProject: (path: string) => Promise<void>
  pollIndexing: () => Promise<void>
  setReady: () => void
}

export const useProjectStore = create<ProjectState>((set, get_) => ({
  projectId: null,
  projectRoot: null,
  codemapDir: null,
  status: 'idle',
  indexingFraction: 0,
  indexingCurrent: '',
  error: null,

  openProject: async (path: string) => {
    set({ status: 'opening', error: null, indexingFraction: 0, indexingCurrent: '' })
    try {
      const resp = await post<OpenProjectResponse>('/api/project', { path })
      set({
        projectId: resp.project_id,
        projectRoot: path,
        codemapDir: resp.codemap_dir,
        status: 'indexing',
      })
      await get_().pollIndexing()
    } catch (err) {
      set({ status: 'error', error: err instanceof Error ? err.message : String(err) })
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
}))
