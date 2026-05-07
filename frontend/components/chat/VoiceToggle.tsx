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
            className={`flex h-10 items-center gap-2 rounded-xl border px-3 transition-colors ${
              enabled
                ? 'border-blue-400/30 bg-blue-500/15 text-blue-100'
                : 'border-white/8 bg-[#07101d] text-white/75'
            }`}
          >
            <Microphone
              className="size-4 shrink-0"
              weight={enabled ? 'fill' : 'regular'}
            />
            <span className="whitespace-nowrap text-xs font-semibold">Voice mode</span>
            <Switch
              id="voice-toggle"
              checked={enabled}
              onCheckedChange={onToggle}
              className="scale-95 data-checked:bg-blue-500"
            />
            {credits !== undefined && credits > 0 && (
              <span className="flex items-center gap-1 text-xs text-white/70">
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
