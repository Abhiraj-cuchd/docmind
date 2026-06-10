'use client';

import { useCallback, useMemo, useRef, useState } from 'react';
import { ChatWindow } from './ChatWindow';
import DocumentPanel from './DocumentPanel';
import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';
import { useDocuments } from '@/hooks/useDocuments';
import { ChunkEvidence, Source } from '@/lib/types';
import { usePDFHighlight } from '@/hooks/usePDFHighlight';

interface ThreePanelLayoutProps {
  activeConversationId: string | null;
  activeDocumentId: string | null;
  activeDocumentIds: string[];
  setSelection: (selection: { conversationId: string | null; documentId: string | null; documentIds?: string[] }) => void;
  updateSelection: (selection: { conversationId?: string | null; documentId?: string | null; documentIds?: string[] }) => void;
  onBack: () => void;
}

export function ThreePanelLayout({
  activeConversationId,
  activeDocumentId,
  activeDocumentIds,
  setSelection,
  updateSelection,
  onBack,
}: ThreePanelLayoutProps) {
  const { createConversation } = useConversationSelection();
  const { documents } = useDocuments();
  const conversationByDocumentIdRef = useRef<Record<string, string>>({});
  const selectedDocumentIds = useMemo(
    () => activeDocumentIds.length > 0
      ? activeDocumentIds
      : activeDocumentId
        ? [activeDocumentId]
        : [],
    [activeDocumentId, activeDocumentIds],
  );

  const referencedDocs = useMemo(
    () => selectedDocumentIds
      .map((documentId) => {
        const doc = documents.find(d => d.id === documentId);
        return doc ? { id: doc.id, filename: doc.filename } : null;
      })
      .filter((doc): doc is { id: string; filename: string } => doc !== null),
    [documents, selectedDocumentIds],
  );
  const [activeSource, setActiveSource] = useState<Source | null>(null);
  const { activeHighlight, triggerHighlight, clearHighlight } = usePDFHighlight();

  const handleSelectDocument = useCallback((documentId: string) => {
    if (documentId === activeDocumentId) {
      // Same document clicked — start a new conversation on it
      setSelection({ conversationId: null, documentId, documentIds: [documentId] });
      return;
    }

    const cachedConversationId = conversationByDocumentIdRef.current[documentId];
    if (cachedConversationId) {
      setSelection({ conversationId: cachedConversationId, documentId, documentIds: [documentId] });
      return;
    }

    setSelection({ conversationId: null, documentId, documentIds: [documentId] });
  }, [activeDocumentId, setSelection]);

  const handleFocusDocument = useCallback((documentId: string) => {
    if (selectedDocumentIds.includes(documentId)) {
      updateSelection({
        documentId,
        documentIds: selectedDocumentIds,
      });
      return;
    }

    handleSelectDocument(documentId);
  }, [handleSelectDocument, selectedDocumentIds, updateSelection]);

  const handleSourceClick = useCallback((source: Source) => {
    if (source.document_id && source.document_id !== activeDocumentId) {
      if (selectedDocumentIds.includes(source.document_id)) {
        updateSelection({ documentId: source.document_id });
      } else {
        handleSelectDocument(source.document_id);
      }
    }
    clearHighlight();
    setActiveSource(source);
  }, [activeDocumentId, clearHighlight, handleSelectDocument, selectedDocumentIds, updateSelection]);

  const handleEvidenceClick = useCallback((evidence: ChunkEvidence) => {
    if (evidence.document_id && evidence.document_id !== activeDocumentId) {
      if (selectedDocumentIds.includes(evidence.document_id)) {
        updateSelection({ documentId: evidence.document_id });
      } else {
        handleSelectDocument(evidence.document_id);
      }
    }
    setActiveSource(null);
    triggerHighlight(evidence);
  }, [activeDocumentId, handleSelectDocument, selectedDocumentIds, triggerHighlight, updateSelection]);

  const handleClearDocuments = useCallback(() => {
    clearHighlight();
    setActiveSource(null);
    setSelection({ conversationId: null, documentId: null, documentIds: [] });
  }, [clearHighlight, setSelection]);

  return (
    <div className="flex h-full overflow-hidden bg-[#060b14] animate-in fade-in-0 duration-300">
      <main className="flex h-full min-w-0 flex-1 flex-col border-r border-white/8 lg:w-[50%] lg:flex-[0_0_50%]">
        <ChatWindow
          conversationId={activeConversationId}
          documentId={activeDocumentId}
          documentIds={selectedDocumentIds}
          referencedDocs={referencedDocs}
          createConversation={createConversation}
          onConversationCreated={(convId) => {
            if (activeDocumentId) {
              conversationByDocumentIdRef.current[activeDocumentId] = convId;
            }
            updateSelection({ conversationId: convId });
          }}
          onBack={onBack}
          onSourceClick={handleSourceClick}
          onEvidenceClick={handleEvidenceClick}
        />
      </main>

      <aside className="hidden h-full flex-shrink-0 lg:flex lg:w-[50%] lg:flex-[0_0_50%]">
        <DocumentPanel
          activeDocumentId={activeDocumentId}
          activeDocumentIds={selectedDocumentIds}
          activeConversationId={activeConversationId}
          referencedDocs={referencedDocs}
          onDocumentSelect={handleFocusDocument}
          onClearAll={handleClearDocuments}
          activeSource={activeSource}
          onClearActiveSource={() => setActiveSource(null)}
          activeHighlight={
            activeHighlight?.documentId === activeDocumentId ||
            activeHighlight?.documentId === null
              ? { content: activeHighlight.content, pageNumber: activeHighlight.pageNumber }
              : null
          }
        />
      </aside>
    </div>
  );
}
