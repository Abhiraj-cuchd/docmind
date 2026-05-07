const DOC_COLORS = [
  { bg: 'bg-blue-500/20',    text: 'text-blue-300',    border: 'border-blue-500/30'    },
  { bg: 'bg-violet-500/20',  text: 'text-violet-300',  border: 'border-violet-500/30'  },
  { bg: 'bg-emerald-500/20', text: 'text-emerald-300', border: 'border-emerald-500/30' },
  { bg: 'bg-amber-500/20',   text: 'text-amber-300',   border: 'border-amber-500/30'   },
  { bg: 'bg-pink-500/20',    text: 'text-pink-300',    border: 'border-pink-500/30'    },
] as const;

export type DocColor = typeof DOC_COLORS[number];

export function getDocColor(documentId: string | null | undefined, allDocIds: string[]): DocColor {
  if (!documentId) return DOC_COLORS[0];
  const idx = allDocIds.indexOf(documentId);
  return DOC_COLORS[Math.max(0, idx) % DOC_COLORS.length];
}

export { DOC_COLORS };
