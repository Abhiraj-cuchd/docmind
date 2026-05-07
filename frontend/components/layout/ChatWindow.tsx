'use client';

import { Component, ReactNode } from 'react';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ChatErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full gap-4 p-8 text-center">
          <div className="w-12 h-12 rounded-2xl bg-destructive/10 border border-destructive/20 flex items-center justify-center">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="text-destructive">
              <path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">Something went wrong</h3>
            <p className="text-xs text-muted-foreground mt-1">{this.state.error?.message}</p>
          </div>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="text-xs text-primary hover:underline"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

import { useEffect, useRef, useState } from 'react';
import { ChunkEvidence, Message, ResponseStyle, Source } from '@/lib/types';
import { useMessages } from '@/hooks/useMessages';
import { useRAGQuery } from '@/hooks/useRAGQuery';
import { useAudioPlayer } from '@/hooks/useAudioPlayer';
import { MessageBubble } from '@/components/chat/MessageBubble';
import { AudioPlayerBar } from '@/components/chat/AudioPlayerBar';
import { ChatInput } from '@/components/chat/ChatInput';
import { TypingIndicator } from '@/components/chat/TypingIndicator';
import { VoiceToggle } from '@/components/chat/VoiceToggle';

import { toast } from 'sonner';
import { v4 as uuidv4 } from 'uuid';
import { ArrowLeft, TextAlignLeft, BookOpen, ChatTeardrop } from '@phosphor-icons/react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

interface ReferencedDoc {
  id: string;
  filename: string;
}

interface ChatWindowProps {
  conversationId: string | null;
  documentId?: string | null;
  documentIds?: string[];
  referencedDocs?: ReferencedDoc[];
  createConversation?: (title: string, documentIds?: string[]) => Promise<import('@/lib/types').Conversation | null>;
  onConversationCreated?: (id: string) => void;
  onBack?: () => void;
  onSourceClick?: (source: Source) => void;
  onEvidenceClick?: (evidence: ChunkEvidence) => void;
}

const STYLES = [
  { value: 'concise',        label: 'Concise',        icon: TextAlignLeft,  tip: 'Short, direct answers'          },
  { value: 'explanatory',    label: 'Explanatory',    icon: BookOpen,       tip: 'Structured breakdown'           },
  { value: 'conversational', label: 'Casual',          icon: ChatTeardrop,   tip: 'Friendly, conversational tone'  },
] as const;

function StyleSwitcher({
  value,
  onChange,
}: {
  value: ResponseStyle;
  onChange: (s: ResponseStyle) => void;
}) {
  return (
    <TooltipProvider delayDuration={400}>
      <div className="flex h-10 items-center gap-1 rounded-xl border border-white/8 bg-[#07101d] p-1">
        {STYLES.map(({ value: v, label, icon: Icon, tip }) => {
          const active = value === v;
          return (
            <Tooltip key={v}>
              <TooltipTrigger asChild>
                <button
                  onClick={() => onChange(v)}
                  className={cn(
                    'flex h-8 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors',
                    active
                      ? 'bg-[#174fbf] text-white shadow-[0_8px_18px_rgba(23,79,191,0.24)]'
                      : 'text-white/65 hover:bg-white/[0.04] hover:text-white',
                  )}
                >
                  <Icon className="size-3.5" weight={active ? 'fill' : 'regular'} />
                  <span>{label}</span>
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="text-xs">{tip}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

function ChatWindowInner({
  conversationId,
  documentId,
  documentIds,
  createConversation,
  onConversationCreated,
  onBack,
  onSourceClick,
  onEvidenceClick,
}: ChatWindowProps) {
  const { messages, loading, addMessage } = useMessages(conversationId);
  const { submit, isLoading, isPolling, abort } = useRAGQuery();
  const player = useAudioPlayer();
  const [voiceMode, setVoiceMode] = useState(false);
  const [voiceCredits, setVoiceCredits] = useState<number | undefined>(undefined);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [responseStyle, setResponseStyle] = useState<ResponseStyle>('explanatory');
  const bottomRef = useRef<HTMLDivElement>(null);
  const hasDoc = !!documentId || (documentIds && documentIds.length > 0);

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Abort on unmount
  useEffect(() => {
    return () => abort();
  }, [abort]);

  useEffect(() => {
    const saved = window.localStorage.getItem('rag_response_style');
    if (saved === 'concise' || saved === 'explanatory' || saved === 'conversational') {
      setResponseStyle(saved);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem('rag_response_style', responseStyle);
  }, [responseStyle]);

  const handleSubmit = async (question: string) => {
    let convId = conversationId;

    if (!convId) {
      if (!hasDoc || !createConversation) {
        toast.error('Select a document to start chatting');
        return;
      }

      const raw = question.trim();
      const title = raw.length > 40 ? `${raw.slice(0, 40).trimEnd()}…` : (raw || 'New Conversation');
      const resolvedDocIds = documentIds ?? (documentId ? [documentId] : []);
      const conv = await createConversation(title, resolvedDocIds);
      if (!conv) {
        toast.error('Failed to create conversation');
        return;
      }

      convId = conv.id;
      onConversationCreated?.(convId);
    }

    // Optimistic user message
    const userMsg: Message = {
      id: uuidv4(),
      conversation_id: convId,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    };
    addMessage(userMsg);

    try {
      const result = await submit({
        question,
        conversation_id: convId,
        voice_mode: voiceMode,
        response_style: responseStyle,
        document_ids: documentIds ?? (documentId ? [documentId] : []),
      });
      if (!result) return;

      // Update voice credits if returned
      if (result.voice_credits_remaining !== undefined) {
        setVoiceCredits(result.voice_credits_remaining);
      }

      const assistantMsg: Message = {
        id: uuidv4(),
        conversation_id: convId,
        role: 'assistant',
        content: result.answer,
        sources: result.sources,
        voice_url: result.voice_url,
        voice_urls: result.voice_urls,
        voice_credits_remaining: result.voice_credits_remaining,
        tokens_used: result.tokens_used,
        path: result.path,
        cached: result.cached,
        created_at: new Date().toISOString(),
      };
      addMessage(assistantMsg);
      setStreamingMessageId(assistantMsg.id);

      // Auto-play voice if returned and voice mode on
      if (voiceMode) {
        const urls = result.voice_urls && result.voice_urls.length > 0
          ? result.voice_urls
          : result.voice_url
            ? [result.voice_url]
            : [];
        if (urls.length > 0) player.play(urls);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Query failed');
    }
  };

  return (
    <div className="flex h-full flex-col bg-[#060b14] text-white">
      <div className="flex h-[68px] shrink-0 items-center justify-between border-b border-white/8 py-0 pl-16 pr-7">
        <div className="flex items-center gap-2">
          {onBack && (
            <button
              onClick={onBack}
              className="rounded-lg p-1.5 text-white/85 transition-colors hover:bg-white/[0.05] hover:text-white"
              aria-label="Back to document selector"
              title="Back to document selector"
            >
              <ArrowLeft className="size-5" />
            </button>
          )}
          <h2 className="text-lg font-semibold tracking-tight">Chat</h2>
          {voiceMode && (
            <span className="rounded-full border border-blue-400/30 bg-blue-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-200">
              Voice mode
            </span>
          )}
          {(isLoading || isPolling) && (
            <span className="animate-pulse text-[10px] text-blue-300/80">
              {isPolling ? 'Searching documents…' : 'Thinking…'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <StyleSwitcher value={responseStyle} onChange={setResponseStyle} />
          <VoiceToggle enabled={voiceMode} onToggle={setVoiceMode} credits={voiceCredits} />
        </div>
      </div>

      <AudioPlayerBar
        isPlaying={player.isPlaying}
        isPaused={player.isPaused}
        onPause={player.pause}
        onResume={player.resume}
        onStop={player.stop}
      />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[860px] space-y-3 px-7 py-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-8 text-center">
              <div className="w-16 h-16 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mb-4">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" className="text-primary">
                  <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-foreground mb-1">Ask MindAgent anything</h3>
              <p className="text-xs text-muted-foreground max-w-xs">
                Upload documents and ask questions. I&apos;ll search through them to find the most relevant answers.
              </p>
            </div>
          ) : (
            messages.map(msg => (
              <MessageBubble
                key={msg.id}
                message={msg}
                documentIds={documentIds}
                isStreaming={msg.id === streamingMessageId && msg.role === 'assistant'}
                onStreamComplete={(id) => {
                  if (id === streamingMessageId) {
                    setStreamingMessageId(null);
                  }
                }}
                onStreamProgress={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })}
                onPlayVoice={player.play}
                onSourceClick={onSourceClick}
                onEvidenceClick={onEvidenceClick}
              />
            ))
          )}

          {(isLoading || isPolling) && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <ChatInput
        onSubmit={handleSubmit}
        onAbort={abort}
        isLoading={isLoading || isPolling}
        disabled={!conversationId && !hasDoc}
        placeholder={
          !conversationId && !hasDoc
            ? 'Select a document to start chatting…'
            : !conversationId
              ? 'Ask a question to start this conversation…'
              : 'Ask a follow-up question...'
        }
      />
    </div>
  );
}

export function ChatWindow(props: ChatWindowProps) {
  return (
    <ChatErrorBoundary>
      <ChatWindowInner {...props} />
    </ChatErrorBoundary>
  );
}
