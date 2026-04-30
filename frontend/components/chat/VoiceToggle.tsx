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
          <div className="flex items-center gap-2">
            <Microphone
              className={`size-4 transition-colors ${enabled ? 'text-primary' : 'text-muted-foreground'}`}
              weight={enabled ? 'fill' : 'regular'}
            />
            <Switch
              id="voice-toggle"
              checked={enabled}
              onCheckedChange={onToggle}
              className="scale-90"
            />
            {credits !== undefined && credits > 0 && (
              <span className="flex items-center gap-0.5 text-xs text-muted-foreground">
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
