export interface NodeResponse {
  id: string
  kind: 'directory' | 'file' | 'class' | 'function' | 'method' | 'external_module'
  name: string
  qualname: string | null
  path: string
  parentId: string | null
  lineStart: number | null
  lineEnd: number | null
  contentHash: string | null
  meta: Record<string, unknown>
}

export interface EdgeResponse {
  id: string
  sourceId: string
  targetId: string
  kind: 'imports' | 'calls' | 'inherits' | 'instantiates' | 'decorates'
  confidence: number
  meta: Record<string, unknown>
}

export interface ProjectStats {
  python_version: string
  venv_path: string | null
  package_manager: string
  dependencies: string[]
  file_counts: Record<string, number>
  loc_total: number
  test_framework: string
  entry_points: string[]
  last_sync_at: string | null
  indexed_file_count: number
  parse_error_count: number
  node_counts: Record<string, number>
}

export interface OpenProjectResponse {
  project_id: string
  codemap_dir: string
  status: 'indexing' | 'ready'
}

export interface IndexingStatus {
  fraction: number
  current: string
  done: boolean
  error: string | null
}

export interface ChildrenResponse {
  nodes: NodeResponse[]
  edges: EdgeResponse[]
}

export interface FsEntry {
  name: string
  path: string
  isDir: boolean
}

export interface BrowseResponse {
  path: string
  parent: string | null
  entries: FsEntry[]
}
