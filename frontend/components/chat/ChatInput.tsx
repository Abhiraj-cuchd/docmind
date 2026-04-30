'use client';

import { useRef, useState, useEffect } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { PaperPlaneTilt, Stop } from '@phosphor-icons/react';
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
    // Reset height
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
    <div className="p-4 border-t border-border/50">
      <div className="relative flex items-end gap-2 bg-card border border-border rounded-2xl p-2 focus-within:border-primary/40 focus-within:ring-1 focus-within:ring-primary/20 transition-all">
        <Textarea
          ref={textareaRef}
          id="chat-input"
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none border-0 bg-transparent p-2 text-sm focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50 min-h-[40px] max-h-[200px]"
        />

        {isLoading ? (
          <Button
            type="button"
            onClick={onAbort}
            size="icon"
            className="shrink-0 rounded-xl bg-destructive/20 hover:bg-destructive/30 text-destructive border-0 mb-1"
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
              'shrink-0 rounded-xl mb-1 border-0 transition-all duration-200',
              value.trim()
                ? 'bg-primary hover:bg-primary/90 text-primary-foreground hover:shadow-lg hover:shadow-primary/20'
                : 'bg-muted text-muted-foreground'
            )}
            title="Send message (Enter)"
          >
            <PaperPlaneTilt className="size-4" weight="fill" />
          </Button>
        )}
      </div>
      <p className="text-center text-[10px] text-muted-foreground/40 mt-2">
        Shift+Enter for new line · Enter to send
      </p>
    </div>
  );
}
