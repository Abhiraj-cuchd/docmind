'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface UseAudioPlayerReturn {
  isPlaying: boolean;
  isPaused: boolean;
  play: (urls: string[]) => void;
  pause: () => void;
  resume: () => void;
  stop: () => void;
}

export function useAudioPlayer(): UseAudioPlayerReturn {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlsRef = useRef<string[]>([]);
  const indexRef = useRef(0);

  const cleanupAudio = useCallback(() => {
    if (!audioRef.current) return;
    audioRef.current.pause();
    audioRef.current.onended = null;
    audioRef.current.onerror = null;
    audioRef.current.src = '';
    audioRef.current = null;
  }, []);

  const stop = useCallback(() => {
    cleanupAudio();
    urlsRef.current = [];
    indexRef.current = 0;
    setIsPlaying(false);
    setIsPaused(false);
  }, [cleanupAudio]);

  const playFromIndex = useCallback((index: number) => {
    const urls = urlsRef.current;
    if (index >= urls.length) {
      stop();
      return;
    }

    indexRef.current = index;
    const audio = new Audio(urls[index]);
    audioRef.current = audio;
    audio.onended = () => playFromIndex(index + 1);
    audio.onerror = () => stop();
    setIsPlaying(true);
    setIsPaused(false);
    audio.play().catch(() => stop());
  }, [stop]);

  const play = useCallback((urls: string[]) => {
    if (!urls || urls.length === 0) {
      stop();
      return;
    }

    stop();
    urlsRef.current = urls;
    playFromIndex(0);
  }, [playFromIndex, stop]);

  const pause = useCallback(() => {
    if (!audioRef.current) return;
    audioRef.current.pause();
    setIsPaused(true);
    setIsPlaying(false);
  }, []);

  const resume = useCallback(() => {
    if (!audioRef.current) return;
    audioRef.current.play()
      .then(() => {
        setIsPlaying(true);
        setIsPaused(false);
      })
      .catch(() => stop());
  }, [stop]);

  useEffect(() => stop, [stop]);

  return {
    isPlaying,
    isPaused,
    play,
    pause,
    resume,
    stop,
  };
}

