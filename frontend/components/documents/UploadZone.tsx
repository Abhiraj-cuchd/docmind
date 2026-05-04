'use client';

import { useCallback, useRef, useState } from 'react';
import { useDocuments } from '@/hooks/useDocuments';
import { useAuth } from '@/hooks/useAuth';
import api from '@/lib/api';
import { Progress } from '@/components/ui/progress';
import { Button } from '@/components/ui/button';
import { CloudArrowUp, FilePdf, X } from '@phosphor-icons/react';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

const MAX_FILE_SIZE_MB = 50;

interface UploadZoneProps {
  onUploadComplete?: () => void;
  compact?: boolean;
}

export function UploadZone({ onUploadComplete, compact }: UploadZoneProps) {
  const { user } = useAuth();
  const { createDocument } = useDocuments();
  const [isDragOver, setIsDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File): string | null => {
    if (file.type !== 'application/pdf') return 'Only PDF files are supported';
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) return `File must be smaller than ${MAX_FILE_SIZE_MB}MB`;
    return null;
  };

  const handleFileSelect = (file: File) => {
    const err = validateFile(file);
    if (err) { toast.error(err); return; }
    setSelectedFile(file);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  }, []);

  const handleUpload = async () => {
    if (!selectedFile || !user) return;
    setUploading(true);
    setProgress(5);

    try {
      // Step 1: Create document record in Supabase
      setStatusText('Creating document record…');
      const doc = await createDocument({ filename: selectedFile.name, userId: user.id });
      if (!doc) throw new Error('Failed to create document record');
      setProgress(20);

      // Step 2: Get presigned URL from Lambda
      setStatusText('Getting upload URL…');
      const { data: presignData } = await api.post<{ upload_url: string }>('/api/upload', {
        filename: selectedFile.name,
        document_id: doc.id,
      });
      setProgress(35);

      // Step 3: Upload file directly to S3
      setStatusText('Uploading to storage…');
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) {
            const pct = 35 + Math.round((e.loaded / e.total) * 55);
            setProgress(pct);
          }
        };
        xhr.onload = () => xhr.status < 400 ? resolve() : reject(new Error(`Upload failed: ${xhr.status}`));
        xhr.onerror = () => reject(new Error('Network error during upload'));
        xhr.open('PUT', presignData.upload_url);
        xhr.setRequestHeader('Content-Type', 'application/pdf');
        xhr.send(selectedFile);
      });

      setProgress(100);
      setStatusText('Upload complete!');
      toast.success(`${selectedFile.name} uploaded successfully`);
      setSelectedFile(null);
      onUploadComplete?.();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
      setProgress(0);
      setStatusText('');
    }
  };

  if (compact) {
    return (
      <div>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={e => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
        />
        <Button
          size="sm"
          variant="outline"
          onClick={() => fileInputRef.current?.click()}
          className="w-full text-xs gap-1.5"
          disabled={uploading}
        >
          <CloudArrowUp className="size-3.5" />
          Upload PDF
        </Button>
        {selectedFile && !uploading && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-xs text-muted-foreground truncate flex-1">{selectedFile.name}</span>
            <Button size="xs" onClick={handleUpload} className="text-xs shrink-0">Upload</Button>
            <button onClick={() => setSelectedFile(null)}>
              <X className="size-3 text-muted-foreground" />
            </button>
          </div>
        )}
        {uploading && (
          <div className="mt-2 space-y-1">
            <Progress value={progress} className="h-1.5" />
            <p className="text-[10px] text-muted-foreground">{statusText}</p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={e => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
      />

      {/* Drop zone */}
      <div
        className={cn('upload-zone rounded-2xl p-8 text-center cursor-pointer', isDragOver && 'drag-over')}
        onDragOver={e => { e.preventDefault(); setIsDragOver(true); }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => !selectedFile && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && fileInputRef.current?.click()}
      >
        <CloudArrowUp className="size-12 mx-auto text-primary/50 mb-3" />
        <p className="text-sm font-medium text-foreground/80">
          Drop your PDF here or <span className="text-primary">browse</span>
        </p>
        <p className="text-xs text-muted-foreground mt-1">PDF only · Max {MAX_FILE_SIZE_MB}MB</p>
      </div>

      {/* Selected file preview */}
      {selectedFile && (
        <div className="flex items-center gap-3 bg-card border border-border rounded-xl p-3">
          <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0">
            <FilePdf className="size-4 text-red-400" weight="fill" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{selectedFile.name}</p>
            <p className="text-xs text-muted-foreground">{(selectedFile.size / 1024 / 1024).toFixed(1)} MB</p>
          </div>
          <button
            onClick={() => setSelectedFile(null)}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
      )}

      {/* Upload progress */}
      {uploading && (
        <div className="space-y-2">
          <Progress value={progress} className="h-2" />
          <p className="text-xs text-muted-foreground text-center">{statusText}</p>
        </div>
      )}

      {/* Upload button */}
      {selectedFile && !uploading && (
        <Button
          onClick={handleUpload}
          className="w-full bg-primary hover:bg-primary/90 text-primary-foreground font-medium h-10 rounded-xl hover:shadow-lg hover:shadow-primary/20 transition-all"
        >
          <CloudArrowUp className="size-4 mr-2" />
          Upload Document
        </Button>
      )}
    </div>
  );
}
