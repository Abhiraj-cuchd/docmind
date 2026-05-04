'use client';

import { Switch } from '@/components/ui/switch';
import { Microphone, Coin } from '@phosphor-icons/react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface VoiceToggleProps {
  enabled: boolean;
  onToggle: (val: boolean) => void;
  credits?: number;
}

export function VoiceToggle({ enabled, onToggle, credits }: VoiceToggleProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`flex items-center gap-2 px-3 py-1.5 rounded-full border transition-colors ${
              enabled
                ? 'bg-primary/15 border-primary/30 text-primary'
                : 'bg-muted/40 border-border/60 text-muted-foreground'
            }`}
          >
            <Microphone
              className="size-4"
              weight={enabled ? 'fill' : 'regular'}
            />
            <span className="text-xs font-semibold tracking-wide">Voice mode</span>
            <Switch
              id="voice-toggle"
              checked={enabled}
              onCheckedChange={onToggle}
              className="scale-100"
            />
            {credits !== undefined && credits > 0 && (
              <span className="flex items-center gap-1 text-xs">
                <Coin className="size-3" />
                {credits}
              </span>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="text-xs">
          {enabled ? 'Voice mode on — responses will be read aloud' : 'Enable voice responses'}
          {credits !== undefined && ` · ${credits} credits remaining`}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
