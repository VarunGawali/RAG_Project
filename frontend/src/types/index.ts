export type RouteType = 'tree' | 'graph' | 'hybrid' | 'summary' | 'search' | 'auto'

export type ContractStatus =
  | 'graph_ready'
  | 'search_only'
  | 'uploading'
  | 'processing'
  | 'failed'

export type UploadStage =
  | 'idle'
  | 'uploading'
  | 'parsing'
  | 'embedding'
  | 'indexing'
  | 'extracting'
  | 'graph_writing'
  | 'done'
  | 'error'

export interface Contract {
  id: string
  displayName: string
  fileName: string
  status: ContractStatus
  uploadedAt: string
  pageCount: number
  fileSize: string
  graphReady: boolean
  clauseCount?: number
  entityCount?: number
}

export interface Citation {
  id: string
  contractId: string
  contractName: string
  clauseTitle: string
  sectionTitle: string
  pageRange: string
  sourcePath: string
  evidenceQuote: string
  route: RouteType
  score?: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  route?: RouteType
  citations?: Citation[]
  contractsQueried?: string[]
  isStreaming?: boolean
  entityCount?: number
  executionMs?: number
  followUpSuggestions?: string[]
}

export interface ChatSession {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  messages: Message[]
  contractFilter: string | null   // null = all contracts
  previewText: string
}

export interface UploadJob {
  id: string
  fileName: string
  fileSize: string
  stage: UploadStage
  progress: number           // 0-100
  contractId?: string
  error?: string
}