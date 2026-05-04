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
import { Message } from '@/lib/types';
import { useMessages } from '@/hooks/useMessages';
import { useRAGQuery } from '@/hooks/useRAGQuery';
import { MessageBubble } from '@/components/chat/MessageBubble';
import { ChatInput } from '@/components/chat/ChatInput';
import { TypingIndicator } from '@/components/chat/TypingIndicator';
import { VoiceToggle } from '@/components/chat/VoiceToggle';

import { toast } from 'sonner';
import { v4 as uuidv4 } from 'uuid';
import { ArrowLeft, ChatCircleDots } from '@phosphor-icons/react';

interface ChatWindowProps {
  conversationId: string | null;
  documentId?: string | null;
  createConversation?: (title: string, documentId?: string) => Promise<import('@/lib/types').Conversation | null>;
  onConversationCreated?: (id: string) => void;
  onBack?: () => void;
}

function ChatWindowInner({
  conversationId,
  documentId,
  createConversation,
  onConversationCreated,
  onBack,
}: ChatWindowProps) {
  const { messages, loading, addMessage } = useMessages(conversationId);
  const { submit, isLoading, isPolling, abort } = useRAGQuery();
  const [voiceMode, setVoiceMode] = useState(false);
  const [voiceCredits, setVoiceCredits] = useState<number | undefined>(undefined);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const playVoiceSequence = async (urls: string[]) => {
    for (const url of urls) {
      await new Promise<void>((resolve, reject) => {
        const audio = new Audio(url);
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error('Audio playback failed'));
        audio.play().catch(reject);
      });
    }
  };

  // Auto-scroll on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Abort on unmount
  useEffect(() => {
    return () => abort();
  }, [abort]);

  const handleSubmit = async (question: string) => {
    let convId = conversationId;

    if (!convId) {
      if (!documentId || !createConversation) {
        toast.error('Select a document to start chatting');
        return;
      }

      const raw = question.trim();
      const title = raw.length > 40 ? `${raw.slice(0, 40).trimEnd()}…` : (raw || 'New Conversation');
      const conv = await createConversation(title, documentId);
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
      const result = await submit({ question, conversation_id: convId, voice_mode: voiceMode });
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

      // Auto-play voice if voice_url present and voice mode on
      if (voiceMode) {
        if (result.voice_urls && result.voice_urls.length > 0) {
          void playVoiceSequence(result.voice_urls).catch(() => {});
        } else if (result.voice_url) {
          new Audio(result.voice_url).play().catch(() => {});
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Query failed');
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className={`px-4 py-3 border-b flex items-center justify-between backdrop-blur-sm ${
          voiceMode
            ? 'bg-primary/5 border-primary/30 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]'
            : 'bg-background/50 border-border/50'
        }`}
      >
        <div className="flex items-center gap-2">
          {onBack && (
            <button
              onClick={onBack}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
              aria-label="Back to document selector"
              title="Back to document selector"
            >
              <ArrowLeft className="size-4" />
            </button>
          )}
          <ChatCircleDots className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-medium">Chat</h2>
          {voiceMode && (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-primary bg-primary/15 border border-primary/30 px-2 py-0.5 rounded-full">
              Voice mode
            </span>
          )}
          {(isLoading || isPolling) && (
            <span className="text-[10px] text-primary/70 animate-pulse">
              {isPolling ? 'Searching documents…' : 'Thinking…'}
            </span>
          )}
        </div>
        <VoiceToggle enabled={voiceMode} onToggle={setVoiceMode} credits={voiceCredits} />
      </div>

      {/* Messages — flex-1 + overflow-y-auto makes this panel independently scrollable */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="py-4 space-y-1">
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
              <h3 className="text-sm font-semibold text-foreground mb-1">Ask DocMind anything</h3>
              <p className="text-xs text-muted-foreground max-w-xs">
                Upload documents and ask questions. I&apos;ll search through them to find the most relevant answers.
              </p>
            </div>
          ) : (
            messages.map(msg => (
              <MessageBubble
                key={msg.id}
                message={msg}
                isStreaming={msg.id === streamingMessageId && msg.role === 'assistant'}
                onStreamComplete={(id) => {
                  if (id === streamingMessageId) {
                    setStreamingMessageId(null);
                  }
                }}
                onStreamProgress={() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' })}
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
        disabled={!conversationId && !documentId}
        placeholder={
          !conversationId && !documentId
            ? 'Select a document to start chatting…'
            : !conversationId
              ? 'Ask a question to start this conversation…'
              : undefined
        }
      />
    </div>
  );
}

export function ChatWindow({ conversationId, documentId, createConversation, onConversationCreated, onBack }: ChatWindowProps) {
  return (
    <ChatErrorBoundary>
      <ChatWindowInner
        conversationId={conversationId}
        documentId={documentId}
        createConversation={createConversation}
        onConversationCreated={onConversationCreated}
        onBack={onBack}
      />
    </ChatErrorBoundary>
  );
}
