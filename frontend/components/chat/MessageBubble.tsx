'use client';

import { Message } from '@/lib/types';
import { Citations } from './Citations';
import { Badge } from '@/components/ui/badge';
import { SpeakerHigh } from '@phosphor-icons/react';
import { useRef } from 'react';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

interface MessageBubbleProps {
  message: Message;
  voiceMode?: boolean;
}

const PATH_LABELS: Record<string, { label: string; color: string }> = {
  rag: { label: 'RAG', color: 'bg-violet-500/15 text-violet-400 border-violet-500/20' },
  direct: { label: 'Direct', color: 'bg-blue-500/15 text-blue-400 border-blue-500/20' },
  cache: { label: 'Cached', color: 'bg-green-500/15 text-green-400 border-green-500/20' },
  conversational: { label: 'Chat', color: 'bg-amber-500/15 text-amber-400 border-amber-500/20' },
};

export function MessageBubble({ message, voiceMode }: MessageBubbleProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const isUser = message.role === 'user';
  const pathInfo = message.path ? PATH_LABELS[message.path] : null;

  const handlePlayVoice = () => {
    if (!message.voice_url) return;
    if (!audioRef.current) {
      audioRef.current = new Audio(message.voice_url);
    }
    audioRef.current.play().catch(console.error);
  };

  return (
    <div className={cn('flex items-start gap-3 px-4 py-2', isUser ? 'flex-row-reverse' : 'flex-row')}>
      {/* Avatar */}
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0 mt-0.5">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-primary">
            <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      )}

      <div className={cn('flex flex-col gap-1.5 max-w-[75%]', isUser ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed',
            isUser
              ? 'message-user rounded-tr-sm'
              : 'message-assistant rounded-tl-sm'
          )}
        >
          <p className="whitespace-pre-wrap">{message.content}</p>

          {/* Citations for assistant messages */}
          {!isUser && message.sources && message.sources.length > 0 && (
            <Citations sources={message.sources} />
          )}
        </div>

        {/* Meta row */}
        <div className={cn('flex items-center gap-2', isUser ? 'flex-row-reverse' : 'flex-row')}>
          {/* Path badge */}
          {pathInfo && (
            <span className={cn(
              'text-[10px] font-medium px-1.5 py-0.5 rounded-md border',
              pathInfo.color
            )}>
              {pathInfo.label}
            </span>
          )}

          {/* Token count */}
          {message.tokens_used && message.tokens_used > 0 && (
            <span className="text-[10px] text-muted-foreground/60">
              {message.tokens_used} tokens
            </span>
          )}

          {/* Timestamp */}
          <span className="text-[10px] text-muted-foreground/50">
            {formatDistanceToNow(new Date(message.created_at), { addSuffix: true })}
          </span>

          {/* Voice button */}
          {!isUser && message.voice_url && (
            <button
              onClick={handlePlayVoice}
              className="text-muted-foreground/60 hover:text-primary transition-colors"
              title="Play audio"
            >
              <SpeakerHigh className="size-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
