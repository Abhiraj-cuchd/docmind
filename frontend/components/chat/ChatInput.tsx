'use client';

import { useRef, useState, useEffect } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { PaperPlaneTilt, Stop, Paperclip } from '@phosphor-icons/react';
import { cn } from '@/lib/utils';

interface ChatInputProps {
  onSubmit: (message: string) => void;
  onAbort?: () => void;
  disabled?: boolean;
  isLoading?: boolean;
  placeholder?: string;
}

export function ChatInput({
  onSubmit,
  onAbort,
  disabled,
  isLoading,
  placeholder = 'Ask anything about your documents…',
}: ChatInputProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || isLoading) return;
    onSubmit(trimmed);
    setValue('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="border-t border-white/8 bg-[#060b14] px-6 pb-5 pt-4">
      <div className="mx-auto flex w-full max-w-[860px] items-end gap-2 rounded-2xl border border-white/8 bg-[#0d1626] p-2 shadow-[0_12px_36px_rgba(0,0,0,0.22)] transition-colors focus-within:border-blue-400/45">
        <button
          type="button"
          className="mb-1 ml-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white/55 transition-colors hover:bg-white/[0.05] hover:text-white"
          title="Attach file"
        >
          <Paperclip className="size-5" />
        </button>
        <Textarea
          ref={textareaRef}
          id="chat-input"
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="min-h-[42px] max-h-[200px] flex-1 resize-none border-0 bg-transparent px-2 py-3 text-sm text-white shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-white/35 disabled:cursor-not-allowed"
        />

        {isLoading ? (
          <Button
            type="button"
            onClick={onAbort}
            size="icon"
            className="mb-1 h-10 w-10 shrink-0 rounded-xl border-0 bg-red-500/20 text-red-300 hover:bg-red-500/30"
            title="Stop generating"
          >
            <Stop className="size-4" weight="fill" />
          </Button>
        ) : (
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={!value.trim() || disabled}
            size="icon"
            className={cn(
              'mb-1 h-10 w-10 shrink-0 rounded-xl border-0 transition-colors',
              value.trim()
                ? 'bg-[#174fbf] text-white hover:bg-[#1f62e2]'
                : 'bg-[#142033] text-white/35'
            )}
            title="Send message (Enter)"
          >
            <PaperPlaneTilt className="size-4" weight="fill" />
          </Button>
        )}
      </div>
      <p className="mt-2 text-center text-[11px] text-white/30">
        Shift + Enter for new line • Enter to send
      </p>
    </div>
  );
}
