'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import { Expand, Minus, Plus, RotateCw, Search } from 'lucide-react';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

export interface HighlightTarget {
  content: string;
  pageNumber: number;
}

interface PDFViewerProps {
  url: string;
  initialPage?: number;
  currentPage?: number;
  highlight?: HighlightTarget | null;
  onPageChange?: (page: number) => void;
  onPageCountChange?: (pages: number) => void;
}

function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/ﬁ/g, 'fi').replace(/ﬂ/g, 'fl')
    .replace(/\s+/g, ' ')
    .replace(/[^\w\s]/g, '')
    .trim();
}

function spanMatchesChunk(spanText: string, normalisedChunk: string): boolean {
  const normSpan = normalise(spanText);
  if (normSpan.length < 4) return false;
  return normalisedChunk.includes(normSpan);
}

export default function PDFViewer({
  url,
  initialPage = 1,
  currentPage,
  highlight,
  onPageChange,
  onPageCountChange,
}: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [uncontrolledPage, setUncontrolledPage] = useState<number>(initialPage);
  const [scale, setScale] = useState<number>(1.05);
  const [rotation, setRotation] = useState<number>(0);
  const [fitMode, setFitMode] = useState<'page' | 'focus'>('page');
  const page = currentPage ?? uncontrolledPage;

  useEffect(() => {
    if (currentPage !== undefined) return;
    setUncontrolledPage(initialPage);
  }, [currentPage, initialPage, url]);

  const normalisedChunkContent = highlight ? normalise(highlight.content) : null;

  const customTextRenderer = useCallback(
    ({ str }: { str: string }) => {
      if (!normalisedChunkContent || !str.trim()) return str;
      if (spanMatchesChunk(str, normalisedChunkContent)) {
        return `<mark style="background:#FDE68A;border-radius:2px;padding:0 1px;">${str}</mark>`;
      }
      return str;
    },
    [normalisedChunkContent],
  );

  const setPage = useCallback((nextPage: number) => {
    const maxPage = numPages || nextPage;
    const clamped = Math.max(1, Math.min(nextPage, maxPage));
    if (currentPage === undefined) {
      setUncontrolledPage(clamped);
    }
    onPageChange?.(clamped);
  }, [currentPage, numPages, onPageChange]);

  useEffect(() => {
    if (!highlight?.pageNumber) return;
    if (highlight.pageNumber !== page) {
      setPage(highlight.pageNumber);
    }
  }, [highlight?.pageNumber, page, setPage]);

  useEffect(() => {
    if (!numPages || page <= numPages) return;
    setPage(numPages);
  }, [numPages, page, setPage]);

  const thumbnailPages = useMemo(() => {
    if (!numPages) return [];
    const start = Math.max(1, page - 2);
    const end = Math.min(numPages, page + 2);
    return Array.from({ length: end - start + 1 }, (_, index) => start + index);
  }, [numPages, page]);

  const handleDocumentLoad = useCallback(({ numPages: totalPages }: { numPages: number }) => {
    setNumPages(totalPages);
    onPageCountChange?.(totalPages);
  }, [onPageCountChange]);

  const increaseZoom = useCallback(() => {
    setScale(value => Math.min(2.5, Number((value + 0.1).toFixed(2))));
  }, []);

  const decreaseZoom = useCallback(() => {
    setScale(value => Math.max(0.5, Number((value - 0.1).toFixed(2))));
  }, []);

  const toggleFitMode = useCallback(() => {
    setFitMode(mode => {
      const nextMode = mode === 'page' ? 'focus' : 'page';
      setScale(nextMode === 'focus' ? 1.25 : 1.05);
      return nextMode;
    });
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-white/8 px-5 py-2 text-xs text-white/65">
        <button
          type="button"
          onClick={() => highlight?.pageNumber && setPage(highlight.pageNumber)}
          disabled={!highlight}
          className="rounded-lg p-1.5 transition-colors hover:bg-white/[0.05] hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
          aria-label="Jump to highlight"
        >
          <Search className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={decreaseZoom}
          className="rounded-lg p-1.5 transition-colors hover:bg-white/[0.05] hover:text-white"
          aria-label="Zoom out"
        >
          <Minus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={increaseZoom}
          className="rounded-lg p-1.5 transition-colors hover:bg-white/[0.05] hover:text-white"
          aria-label="Zoom in"
        >
          <Plus className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={toggleFitMode}
          className="min-w-[72px] rounded-xl border border-white/8 bg-[#091321] px-3 py-1.5 text-sm text-white/85 transition-colors hover:bg-white/[0.05]"
          title={fitMode === 'page' ? 'Focus mode' : 'Fit page'}
        >
          {Math.round(scale * 100)}%
        </button>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={toggleFitMode}
            className="rounded-lg p-1.5 transition-colors hover:bg-white/[0.05] hover:text-white"
            aria-label={fitMode === 'page' ? 'Focus mode' : 'Fit page'}
          >
            <Expand className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setRotation(value => (value + 90) % 360)}
            className="rounded-lg p-1.5 transition-colors hover:bg-white/[0.05] hover:text-white"
            aria-label="Rotate page"
          >
            <RotateCw className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <Document
          file={url}
          onLoadSuccess={handleDocumentLoad}
          className="flex min-h-0 flex-1"
          loading={
            <div className="flex h-full flex-1 items-center justify-center py-12 text-sm text-white/55">
              Loading PDF…
            </div>
          }
          error={
            <div className="flex h-full flex-1 items-center justify-center py-12 text-sm text-red-400">
              Failed to load PDF.
            </div>
          }
        >
          <div className="flex min-h-0 flex-1">
            <div className="flex w-[116px] shrink-0 flex-col border-r border-white/8 bg-[#07101d] px-3 py-3">
              <div className="space-y-3 overflow-y-auto pr-1">
                {thumbnailPages.map((pageNumber) => {
                  const active = pageNumber === page;

                  return (
                    <button
                      key={pageNumber}
                      type="button"
                      onClick={() => setPage(pageNumber)}
                      className="block w-full text-center"
                    >
                      <div className={active ? 'overflow-hidden rounded-xl border border-[#3468d8] bg-[#1b3d86]' : 'overflow-hidden rounded-xl border border-white/8 bg-white/[0.03]'}>
                        <div className="flex justify-center bg-white px-1 py-2">
                          <Page
                            pageNumber={pageNumber}
                            width={70}
                            rotate={rotation}
                            renderAnnotationLayer={false}
                            renderTextLayer={false}
                          />
                        </div>
                      </div>
                      <p className={active ? 'mt-2 text-sm text-white' : 'mt-2 text-sm text-white/45'}>
                        {pageNumber}
                      </p>
                    </button>
                  );
                })}
              </div>

              {thumbnailPages.length > 0 && thumbnailPages[thumbnailPages.length - 1] < numPages ? (
                <button
                  type="button"
                  onClick={() => setPage(Math.min(numPages, page + 5))}
                  className="mt-3 rounded-lg p-2 text-white/50 transition-colors hover:bg-white/[0.05] hover:text-white"
                >
                  v
                </button>
              ) : null}
            </div>

            <div className="min-h-0 flex-1 overflow-auto bg-[#09111c] p-4">
              <div className="flex min-h-full items-start justify-center">
                <div className="rounded-[20px] bg-white p-4 shadow-[0_24px_60px_rgba(0,0,0,0.45)]">
                  <Page
                    pageNumber={page}
                    scale={scale}
                    rotate={rotation}
                    customTextRenderer={customTextRenderer}
                    renderAnnotationLayer={false}
                  />
                </div>
              </div>
            </div>
          </div>
        </Document>
      </div>
    </div>
  );
}
