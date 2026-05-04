# Implementation Plan

Two features:
1. **Lazy conversation creation** — conversation is created on first query submit, named after the query
2. **Google OAuth** — "Continue with Google" on login and register pages via Supabase

---

## Feature 1 — Lazy Conversation Creation

### Context: current vs desired flow

**Current:**
```
User clicks doc → createConversation(filename, documentId) → setSelection → /chat
```
Conversation is created eagerly on document selection, title = filename.

**Desired:**
```
User clicks doc → setSelection({ conversationId: null, documentId }) → /chat
  → user types first query
  → createConversation(query[:40], documentId) → convId
  → submit query with convId
```
Conversation is created lazily on first submit, title = first 40 chars of query.

---

### Task 1.1 — `app/(protected)/dashboard/page.tsx`

**What to change:** Remove conversation creation. Only check for existing
conversations (from a previous session). If one exists for this doc, reuse it.
If not, navigate with `conversationId: null` — let ChatWindow create it.

```diff
- const { conversations, createConversation } = useConversations();
+ const { conversations } = useConversations();
- const conversationPromiseByDocumentIdRef = useRef<...>({});

  const handleSelectDocument = useCallback(async (documentId: string, filename: string) => {
    const existingConversation = conversations.find(conv => conv.document_id === documentId);
    if (existingConversation) {
      setSelection({ conversationId: existingConversation.id, documentId });
      router.push('/chat');
      return;
    }

-   // ... all the createConversation + promise dedup logic
-   toast.error('Failed to create conversation');

+   // No existing conv — navigate with null conversationId; ChatWindow creates it
+   setSelection({ conversationId: null, documentId });
+   router.push('/chat');
  }, [conversations, router, setSelection]);
```

---

### Task 1.2 — `app/(protected)/layout.tsx`

**What to change:** The "New conversation" button in the sidebar currently
creates a blank `"New Conversation"` record immediately. Change it to clear
selection and navigate to `/dashboard` so the user picks a document first.

```diff
+ import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';

  function ProtectedShell(...) {
    const router = useRouter();
-   const { conversations, loading, createConversation } = useConversations();
+   const { conversations, loading } = useConversations();
    const { selection, setSelection } = useConversationSelection();
+   const { clearSelection } = useConversationSelection();  // or add to existing destructure

-   const handleNewConversation = useCallback(async () => {
-     const conv = await createConversation('New Conversation');
-     if (conv) {
-       setSelection({ conversationId: conv.id, documentId: conv.document_id ?? null });
-       router.push('/chat');
-     }
-   }, [createConversation, router, setSelection]);

+   const handleNewConversation = useCallback(() => {
+     clearSelection();
+     router.push('/dashboard');
+   }, [clearSelection, router]);
```

---

### Task 1.3 — `components/layout/ThreePanelLayout.tsx`

**What to change:**
- Remove conversation creation from `handleSelectDocument` — same lazy logic
- Cache convIds that were created by ChatWindow (via `onConversationCreated`)
- Pass `createConversation`, `documentId`, and `onConversationCreated` down to ChatWindow
- Update `ThreePanelLayoutProps` interface

**New props interface:**
```typescript
interface ThreePanelLayoutProps {
  activeConversationId: string | null;
  activeDocumentId: string | null;
  setSelection: (s: { conversationId: string | null; documentId: string | null }) => void;
  updateSelection: (s: { conversationId?: string | null; documentId?: string | null }) => void;
  onBack: () => void;
}
```
(Unchanged — `createConversation` is sourced internally via `useConversations`.)

**`handleSelectDocument` rewrite:**
```typescript
const handleSelectDocument = useCallback((documentId: string) => {
  // Already on this doc with a live conversation
  if (documentId === activeDocumentId && activeConversationId) return;

  // Previously created a conv for this doc in this session
  const cached = conversationByDocumentIdRef.current[documentId];
  if (cached) {
    setSelection({ conversationId: cached, documentId });
    return;
  }

  // No existing — lazy: set doc, null conversation
  setSelection({ conversationId: null, documentId });
}, [activeDocumentId, activeConversationId, setSelection]);
```
Remove all promise-dedup logic and `createConversation` call.

**ChatWindow call site — add new props:**
```tsx
<ChatWindow
  conversationId={activeConversationId}
  documentId={activeDocumentId}          // new
  createConversation={createConversation} // from useConversations
  onConversationCreated={(id) => {        // new
    if (activeDocumentId) {
      conversationByDocumentIdRef.current[activeDocumentId] = id;
    }
    updateSelection({ conversationId: id });
  }}
  onBack={onBack}
/>
```

---

### Task 1.4 — `components/layout/ChatWindow.tsx`

This is the core change. `ChatWindowInner` receives new props and handles
lazy creation inside `handleSubmit`.

**Updated props interface:**
```typescript
interface ChatWindowProps {
  conversationId: string | null;
  documentId?: string | null;                   // new
  createConversation?: (                        // new
    title: string,
    documentId?: string
  ) => Promise<import('@/lib/types').Conversation | null>;
  onConversationCreated?: (id: string) => void; // new
  onBack?: () => void;
}
```

**`handleSubmit` rewrite:**
```typescript
const handleSubmit = async (question: string) => {
  // Step 1: resolve (or lazily create) the conversation
  let convId = conversationId;

  if (!convId) {
    if (!documentId || !createConversation) {
      toast.error('Select a document to start chatting');
      return;
    }
    const raw = question.trim();
    const title =
      raw.length > 40 ? raw.slice(0, 40).trimEnd() + '…' : raw || 'New Conversation';

    const conv = await createConversation(title, documentId);
    if (!conv) {
      toast.error('Failed to create conversation');
      return;
    }
    convId = conv.id;
    onConversationCreated?.(convId);
  }

  // Step 2: optimistic user message (use resolved convId, not prop)
  const userMsg: Message = {
    id: uuidv4(),
    conversation_id: convId,
    role: 'user',
    content: question,
    created_at: new Date().toISOString(),
  };
  addMessage(userMsg);

  try {
    const result = await submit({
      question,
      conversation_id: convId,   // resolved convId
      voice_mode: voiceMode,
    });
    if (!result) return;

    // ... rest unchanged (voice credits, assistantMsg, etc.)
  } catch (err) {
    toast.error(err instanceof Error ? err.message : 'Query failed');
  }
};
```

**`ChatInput` disabled/placeholder logic:**
```tsx
// Was: disabled={!conversationId}
// New: allow input when documentId is set (conversation will be created lazily)

disabled={!conversationId && !documentId}
placeholder={
  !conversationId && !documentId
    ? 'Select a document to start chatting…'
    : !conversationId
      ? 'Ask a question to start this conversation…'
      : undefined
}
```

---

### Task 1.5 — Verify `useConversations.ts` refresh

When `createConversation` is called inside ChatWindow, it already calls
`setConversations(prev => [created, ...prev])` — so the sidebar list
updates immediately without a re-fetch. No changes needed here.

---

## Feature 2 — Google OAuth

### Task 2.1 — Supabase Dashboard (manual, one-time)

1. Open Supabase Dashboard → **Authentication → Providers → Google**
2. Toggle **Enable Sign in with Google**
3. Copy the **Callback URL** shown there (looks like
   `https://juzxjfnjysbzymbijzsv.supabase.co/auth/v1/callback`)
4. Leave the page open — you'll paste credentials into it in step 2.3

---

### Task 2.2 — Google Cloud Console (manual, one-time)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create (or select) a project → **APIs & Services → OAuth consent screen**
   - User type: **External**
   - App name: `DocMind`, fill required fields, save
3. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorized redirect URI: paste the Supabase Callback URL from Task 2.1
4. Copy the generated **Client ID** and **Client Secret**

---

### Task 2.3 — Complete Supabase Google Provider setup (manual)

Back in Supabase Dashboard → Authentication → Providers → Google:
- Paste **Client ID** and **Client Secret**
- Save

Then go to **Authentication → URL Configuration**:
- **Site URL**: `http://localhost:3000` (dev) / your production URL
- **Additional Redirect URLs**: add `http://localhost:3000/**` and production
  equivalent

---

### Task 2.4 — Create `app/auth/callback/route.ts` (new file)

This is the PKCE code-exchange endpoint. Supabase redirects here after
Google completes OAuth with `?code=...` in the URL.

```typescript
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')

  if (code) {
    const cookieStore = cookies()
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return cookieStore.getAll()
          },
          setAll(cookiesToSet) {
            try {
              cookiesToSet.forEach(({ name, value, options }) =>
                cookieStore.set(name, value, options)
              )
            } catch {}
          },
        },
      }
    )

    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      return NextResponse.redirect(`${origin}/dashboard`)
    }
  }

  return NextResponse.redirect(`${origin}/login?error=auth_failed`)
}
```

Note: this file lives at `app/auth/callback/route.ts`, outside the `(auth)`
route group, so it becomes a plain API route at `/auth/callback`.

---

### Task 2.5 — Update `middleware.ts`

The current middleware redirects unauthenticated users to `/login` for all
paths that don't start with `/login`, `/register`, or `/api`. The callback
route at `/auth/callback` would be caught and redirected, breaking OAuth.

```diff
  if (
    !user &&
    !request.nextUrl.pathname.startsWith('/login') &&
    !request.nextUrl.pathname.startsWith('/register') &&
+   !request.nextUrl.pathname.startsWith('/auth') &&
    !request.nextUrl.pathname.startsWith('/api')
  ) {
```

---

### Task 2.6 — Update `app/(auth)/login/page.tsx`

Add a `handleGoogleSignIn` function and a Google button with a divider.

**New handler (add to component):**
```typescript
const handleGoogleSignIn = async () => {
  const { error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
      redirectTo: `${window.location.origin}/auth/callback`,
    },
  });
  if (error) toast.error(error.message);
};
```

**UI additions (inside the card, after the `<form>` and before the register link):**
```tsx
{/* Divider */}
<div className="relative my-5">
  <div className="absolute inset-0 flex items-center">
    <div className="w-full border-t border-border" />
  </div>
  <div className="relative flex justify-center text-xs">
    <span className="bg-card px-3 text-muted-foreground">or continue with</span>
  </div>
</div>

{/* Google button */}
<button
  type="button"
  onClick={handleGoogleSignIn}
  className="w-full flex items-center justify-center gap-3 h-10 rounded-xl border border-border bg-background hover:bg-accent transition-colors text-sm font-medium"
>
  {/* Google SVG logo */}
  <svg width="18" height="18" viewBox="0 0 24 24">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
  </svg>
  Continue with Google
</button>
```

---

### Task 2.7 — Update `app/(auth)/register/page.tsx`

Identical Google button and handler as Task 2.6. Copy the same
`handleGoogleSignIn` function and the same divider + button UI block.

The button text can stay "Continue with Google" — Supabase handles
both sign-in and sign-up through the same OAuth flow; new users get
auto-provisioned via the `on_auth_user_created` trigger.

---

## Implementation Order

1. Task 1.1 → 1.2 → 1.3 → 1.4 → 1.5 (do in this order, they build on each other)
2. Task 2.1 → 2.2 → 2.3 (manual, do before testing OAuth)
3. Task 2.4 → 2.5 → 2.6 → 2.7 (code changes, order doesn't matter)

---

## Edge Cases to Watch

| Case | Handling |
|------|----------|
| User selects doc, goes to chat, immediately hits back without typing | `conversationId` stays null, no orphaned record created |
| User selects same doc again from right panel | `conversationByDocumentIdRef` check returns cached convId (if conversation was already created); otherwise null (new lazy conversation) |
| Existing conversation from sidebar (has `document_id`) | `handleSelectConversation` already sets `{conversationId: conv.id, documentId: conv.document_id}` — no change needed |
| Conversation with no `document_id` (older data or "New Conversation") | `documentId` will be null in ChatWindow; input disabled correctly |
| OAuth user first login — `user_profiles` auto-provision | Handled by existing `on_auth_user_created` trigger in `007_triggers.sql` — no code changes needed |
| OAuth error redirect (`/login?error=auth_failed`) | Login page ignores the query param visually (no current error display) — optionally add `useSearchParams` to toast it |
