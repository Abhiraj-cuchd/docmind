'use client';

import { Message } from '@/lib/types';
import { Citations } from './Citations';
import { SpeakerHigh } from '@phosphor-icons/react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
  onStreamComplete?: (messageId: string) => void;
  onStreamProgress?: () => void;
}

const PATH_LABELS: Record<string, { label: string; color: string }> = {
  rag: { label: 'RAG', color: 'bg-violet-500/15 text-violet-400 border-violet-500/20' },
  direct: { label: 'Direct', color: 'bg-blue-500/15 text-blue-400 border-blue-500/20' },
  cache: { label: 'Cached', color: 'bg-green-500/15 text-green-400 border-green-500/20' },
  conversational: { label: 'Chat', color: 'bg-amber-500/15 text-amber-400 border-amber-500/20' },
};

export function MessageBubble({ message, isStreaming, onStreamComplete, onStreamProgress }: MessageBubbleProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const isUser = message.role === 'user';
  const pathInfo = message.path ? PATH_LABELS[message.path] : null;
  const [displayText, setDisplayText] = useState(message.content);

  const prefersReducedMotion = useMemo(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }, []);

  const handlePlayVoice = () => {
    const urls = message.voice_urls && message.voice_urls.length > 0
      ? message.voice_urls
      : message.voice_url
        ? [message.voice_url]
        : [];

    if (urls.length === 0) return;

    let index = 0;
    const playNext = () => {
      audioRef.current = new Audio(urls[index]);
      audioRef.current.onended = () => {
        index += 1;
        if (index < urls.length) {
          playNext();
        }
      };
      audioRef.current.play().catch(console.error);
    };

    playNext();
  };

  useEffect(() => {
    setDisplayText(message.content);
  }, [message.content, message.id]);

  useEffect(() => {
    if (isUser) return;
    if (!message.content) return;
    if (prefersReducedMotion) return;

    if (!isStreaming) {
      setDisplayText(message.content);
      return;
    }

    let index = 0;
    const fullText = message.content;
    setDisplayText('');

    const interval = window.setInterval(() => {
      index += 1;
      setDisplayText(fullText.slice(0, index));
      onStreamProgress?.();

      if (index >= fullText.length) {
        window.clearInterval(interval);
        onStreamComplete?.(message.id);
      }
    }, 16);

    return () => window.clearInterval(interval);
  }, [isStreaming, isUser, message.content, message.id, onStreamComplete, onStreamProgress, prefersReducedMotion]);

  const formattedContent = isUser ? (
    <p className="whitespace-pre-wrap">{message.content}</p>
  ) : (
    <div className="assistant-content">{renderFormattedText(displayText)}</div>
  );

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
          {formattedContent}

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
          {!isUser && (message.voice_url || (message.voice_urls && message.voice_urls.length > 0)) && (
            <button
              onClick={handlePlayVoice}
              className="flex items-center gap-1 px-2 py-1 rounded-md border border-primary/30 bg-primary/10 text-primary text-[10px] font-medium hover:bg-primary/15 transition-colors"
              title="Play audio"
            >
              <SpeakerHigh className="size-3.5" />
              Play audio
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function renderFormattedText(text: string) {
  if (!text) return null;

  const blocks = text.split(/\n\n+/g);

  return blocks.map((block, blockIndex) => {
    const lines = block.split('\n');
    const isUnordered = lines.every(line => /^\s*[-*]\s+/.test(line));
    const isOrdered = lines.every(line => /^\s*\d+\.\s+/.test(line));

    if (isUnordered) {
      return (
        <ul key={`ul-${blockIndex}`} className="list-disc pl-5 space-y-1">
          {lines.map((line, lineIndex) => {
            const { content, indent } = parseListItem(line, /^\s*[-*]\s+/);
            return (
              <li key={`ul-${blockIndex}-${lineIndex}`} style={{ marginLeft: indent * 16 }}>
                {renderInline(content)}
              </li>
            );
          })}
        </ul>
      );
    }

    if (isOrdered) {
      return (
        <ol key={`ol-${blockIndex}`} className="list-decimal pl-5 space-y-1">
          {lines.map((line, lineIndex) => {
            const { content, indent } = parseListItem(line, /^\s*\d+\.\s+/);
            return (
              <li key={`ol-${blockIndex}-${lineIndex}`} style={{ marginLeft: indent * 16 }}>
                {renderInline(content)}
              </li>
            );
          })}
        </ol>
      );
    }

    return (
      <p key={`p-${blockIndex}`} className="whitespace-pre-wrap">
        {renderInline(block)}
      </p>
    );
  });
}

function parseListItem(line: string, pattern: RegExp) {
  const leadingSpaces = line.match(/^\s*/)?.[0]?.length ?? 0;
  const indent = Math.floor(leadingSpaces / 2);
  const content = line.replace(pattern, '').trim();
  return { content, indent };
}

function renderInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={`b-${index}`}>{part.slice(2, -2)}</strong>;
    }
    return <span key={`t-${index}`}>{part}</span>;
  });
}
