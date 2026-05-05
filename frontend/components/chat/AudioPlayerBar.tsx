'use client';

import { Pause, Play, StopCircle, SpeakerHigh } from '@phosphor-icons/react';

interface AudioPlayerBarProps {
  isPlaying: boolean;
  isPaused: boolean;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
}

export function AudioPlayerBar({ isPlaying, isPaused, onPause, onResume, onStop }: AudioPlayerBarProps) {
  if (!isPlaying && !isPaused) return null;

  return (
    <div className="flex items-center gap-2 px-4 py-1.5 bg-primary/10 border-b border-primary/20 text-primary text-xs">
      <SpeakerHigh className="size-3.5 shrink-0 animate-pulse" />
      <span className="flex-1 font-medium">{isPaused ? 'Audio paused' : 'Playing audio…'}</span>
      {isPlaying && (
        <button
          onClick={onPause}
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-primary/30 hover:bg-primary/15 transition-colors"
          title="Pause"
        >
          <Pause className="size-3" />
          Pause
        </button>
      )}
      {isPaused && (
        <button
          onClick={onResume}
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-primary/30 hover:bg-primary/15 transition-colors"
          title="Resume"
        >
          <Play className="size-3" />
          Resume
        </button>
      )}
      <button
        onClick={onStop}
        className="flex items-center gap-1 px-2 py-0.5 rounded border border-primary/30 hover:bg-primary/15 transition-colors"
        title="Stop"
      >
        <StopCircle className="size-3" />
        Stop
      </button>
    </div>
  );
}
