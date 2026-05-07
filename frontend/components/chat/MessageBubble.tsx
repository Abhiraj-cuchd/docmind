'use client';

import { ChunkEvidence, Message } from '@/lib/types';
import { Citations } from './Citations';
import { SpeakerHigh } from '@phosphor-icons/react';
import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { BrainCircuit, UserRound } from 'lucide-react';

interface MessageBubbleProps {
  message: Message;
  documentIds?: string[];
  isStreaming?: boolean;
  onStreamComplete?: (messageId: string) => void;
  onStreamProgress?: () => void;
  onPlayVoice?: (urls: string[]) => void;
  onSourceClick?: (source: import('@/lib/types').Source) => void;
  onEvidenceClick?: (evidence: ChunkEvidence) => void;
}

const PATH_LABELS: Record<string, { label: string; color: string }> = {
  rag: { label: 'RAG', color: 'bg-violet-500/15 text-violet-400 border-violet-500/20' },
  direct: { label: 'Direct', color: 'bg-blue-500/15 text-blue-400 border-blue-500/20' },
  cache: { label: 'Cached', color: 'bg-green-500/15 text-green-400 border-green-500/20' },
  conversational: { label: 'Chat', color: 'bg-amber-500/15 text-amber-400 border-amber-500/20' },
  rag_fallback: { label: 'General Knowledge', color: 'bg-orange-500/15 text-orange-400 border-orange-500/20' },
};

export function MessageBubble({ message, documentIds, isStreaming, onStreamComplete, onStreamProgress, onPlayVoice, onSourceClick, onEvidenceClick }: MessageBubbleProps) {
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
    if (urls.length > 0) onPlayVoice?.(urls);
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

  if (isUser) {
    return (
      <div className="w-full py-2">
        <div className="mx-auto flex max-w-[640px] items-start gap-3 rounded-xl border border-white/6 bg-[#111a2a] px-5 py-4 text-[17px] leading-7 text-white shadow-[0_16px_36px_rgba(0,0,0,0.18)]">
          <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#5b5cf6] text-white shadow-[0_0_0_1px_rgba(255,255,255,0.12)]">
            <UserRound className="h-4 w-4" />
          </div>
          <p className="whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  const formattedContent = (
    <div className="assistant-content">{renderFormattedText(displayText)}</div>
  );

  return (
    <div className="flex w-full items-start gap-4 py-1">
      <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#174fbf] text-white shadow-[0_0_0_1px_rgba(96,165,250,0.25)]">
        <BrainCircuit className="h-5 w-5" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="text-[17px] leading-7 text-white/92">
          {formattedContent}

          {message.sources && message.sources.length > 0 && (
            <Citations
              sources={message.sources}
              retrievedChunks={message.retrieved_chunks}
              documentIds={documentIds}
              onSourceClick={onSourceClick}
              onEvidenceClick={onEvidenceClick}
            />
          )}
        </div>

        {(pathInfo || message.tokens_used || message.voice_url || (message.voice_urls && message.voice_urls.length > 0)) && (
        <div className="mt-2 flex items-center gap-2">
          {pathInfo && (
            <span className={cn(
              'text-[10px] font-medium px-1.5 py-0.5 rounded-md border',
              pathInfo.color
            )}>
              {pathInfo.label}
            </span>
          )}

          {message.tokens_used && message.tokens_used > 0 && (
            <span className="text-[10px] text-white/35">
              {message.tokens_used} tokens
            </span>
          )}

          {(message.voice_url || (message.voice_urls && message.voice_urls.length > 0)) && (
            <button
              onClick={handlePlayVoice}
              className="flex items-center gap-1 rounded-md border border-blue-400/30 bg-blue-500/10 px-2 py-1 text-[10px] font-medium text-blue-200 transition-colors hover:bg-blue-500/15"
              title="Play audio"
            >
              <SpeakerHigh className="size-3.5" />
              Play audio
            </button>
          )}
        </div>
        )}
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

    // Basic Markdown Table support
    if (lines.length >= 2 && lines[0].includes('|') && lines[1].includes('|') && lines[1].includes('-')) {
      const rows = lines.filter(line => line.includes('|')).map(line =>
        line.split('|').map(cell => cell.trim()).filter((_, i, arr) => {
          // Remove empty first/last elements if line starts/ends with |
          if (i === 0 && arr[0] === '') return false;
          if (i === arr.length - 1 && arr[arr.length - 1] === '') return false;
          return true;
        })
      );
      if (rows.length >= 2) {
        const headers = rows[0];
        const dataRows = rows.slice(2); // Skip separator row
        return (
          <div key={`table-${blockIndex}`} className="my-4 overflow-x-auto rounded-xl border border-white/10 bg-[#09111f]">
            <table className="w-full text-left text-[15px]">
              <thead className="border-b border-white/10 bg-[#0d1726] text-white">
                <tr>
                  {headers.map((h, i) => (
                    <th key={`th-${i}`} className="px-4 py-3 font-semibold">{renderInline(h)}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/8 text-white/90">
                {dataRows.map((row, rIdx) => (
                  <tr key={`tr-${rIdx}`} className="transition-colors hover:bg-white/[0.03]">
                    {row.map((cell, cIdx) => (
                      <td key={`td-${rIdx}-${cIdx}`} className="break-words px-4 py-3 align-top">
                        {renderInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
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
