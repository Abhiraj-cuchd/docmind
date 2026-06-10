export interface Conversation {
  id: string;
  user_id: string;
  title: string;
  document_id?: string | null;
  documentIds?: string[];
  summary?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Source {
  chunk_id: string | null;
  document_id: string | null;
  page_number: number | null;
  filename: string;
  section: string | null;
  snippet: string;
}

export interface ChunkEvidence {
  id: string;
  document_id: string | null;
  content: string;
  page_number: number | null;
  filename: string;
  section: string | null;
  rrf_score?: number;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  retrieved_chunks?: ChunkEvidence[];
  voice_url?: string | null;
  voice_urls?: string[] | null;
  voice_credits_remaining?: number;
  tokens_used?: number;
  path?: 'rag' | 'direct' | 'cache' | 'conversational' | 'rag_fallback';
  cached?: boolean;
  created_at: string;
}

export type DocumentStatus = 'processing' | 'indexing' | 'ready' | 'failed' | 'partial';

export interface Document {
  id: string;
  user_id: string;
  filename: string;
  s3_key: string;
  status: DocumentStatus;
  chunk_count?: number;
  skipped_pages?: number;
  created_at: string;
  updated_at: string;
}

export interface QueryRequest {
  question: string;
  conversation_id: string;
  voice_mode: boolean;
  response_style?: ResponseStyle;
  document_ids?: string[];
}

export interface QueryResponse {
  job_id?: string;
  status?: 'done' | 'pending' | 'error';
  answer?: string;
  cached?: boolean;
  voice_url?: string | null;
  voice_urls?: string[] | null;
  voice_credits_remaining?: number;
  tokens_used?: number;
  path?: 'rag' | 'direct' | 'cache' | 'conversational' | 'rag_fallback';
  sources?: Source[];
}

export interface PollResult {
  status: 'done' | 'pending' | 'error';
  answer: string;
  cached: boolean;
  voice_url: string | null;
  voice_urls?: string[] | null;
  voice_credits_remaining: number;
  tokens_used: number;
  path: 'rag' | 'direct' | 'cache' | 'conversational' | 'rag_fallback';
  sources?: Source[];
}

export interface UploadPresignResponse {
  presigned_url: string;
  document_id: string;
}

export type ResponseStyle = 'concise' | 'explanatory' | 'conversational';

// ── Generation features ───────────────────────────────────────────────

export type GenerateTaskType =
  | 'summarize_conversation'
  | 'summarize_document'
  | 'generate_flashcards';

export interface GenerateRequest {
  task_type: GenerateTaskType;
  conversation_id?: string;
  document_id?: string;
}

export interface GenerateResponse {
  job_id: string;
  status: 'pending';
}

export interface GeneratePollResult {
  status: 'done' | 'error';
  summary?: string;
  strategy?: 'stuff' | 'map_reduce';
  deck_id?: string;
  count?: number;
  message?: string;
}

export interface Summary {
  id: string;
  source_type: 'conversation' | 'document';
  conversation_id: string | null;
  document_id: string | null;
  content: string;
  created_at: string;
}

export interface Flashcard {
  id: string;
  deck_id: string;
  question: string;
  answer: string;
}

export interface FlashcardDeck {
  id: string;
  source_type: 'conversation' | 'document';
  conversation_id: string | null;
  document_id: string | null;
  title: string;
  created_at: string;
  cards: Flashcard[];
}
