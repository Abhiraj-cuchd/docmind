export interface Conversation {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Source {
  filename: string;
  page: number;
  score?: number;
  chunk_text?: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Source[];
  voice_url?: string | null;
  voice_credits_remaining?: number;
  tokens_used?: number;
  path?: 'rag' | 'direct' | 'cache' | 'conversational';
  cached?: boolean;
  created_at: string;
}

export type DocumentStatus = 'processing' | 'indexing' | 'ready' | 'failed';

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
}

export interface QueryResponse {
  job_id?: string;
  status?: 'done' | 'pending' | 'error';
  answer?: string;
  cached?: boolean;
  voice_url?: string | null;
  voice_credits_remaining?: number;
  tokens_used?: number;
  path?: 'rag' | 'direct' | 'cache' | 'conversational';
  sources?: Source[];
}

export interface PollResult {
  status: 'done' | 'pending' | 'error';
  answer: string;
  cached: boolean;
  voice_url: string | null;
  voice_credits_remaining: number;
  tokens_used: number;
  path: 'rag' | 'direct' | 'cache' | 'conversational';
  sources?: Source[];
}

export interface UploadPresignResponse {
  presigned_url: string;
  document_id: string;
}
