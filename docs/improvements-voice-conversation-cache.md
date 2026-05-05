# Improvement Plan: Voice Controls, Conversation Reset, Cache+Voice, General Knowledge Fallback

## Overview

Four independent bugs, each with a distinct root cause. Fixes span frontend components and two backend Lambdas.

---

## Bug 1 — Voice Playback Has No User Controls

### What's broken

Once audio starts playing, the user cannot pause, resume, or stop it.

### Root cause (exact code)

**`ChatWindow.tsx:84-93` — `playVoiceSequence`**
```ts
const playVoiceSequence = async (urls: string[]) => {
  for (const url of urls) {
    await new Promise<void>((resolve, reject) => {
      const audio = new Audio(url);  // ← created inline, no ref stored
      audio.play().catch(reject);
    });
  }
};
```
Audio objects are created inside a loop and discarded. No reference is kept. Calling code is fire-and-forget:
```ts
void playVoiceSequence(result.voice_urls).catch(() => {});  // line 165
```
No handle to call `.pause()` or `.pause()` on later.

**`MessageBubble.tsx:35-57` — manual play button**
```ts
audioRef.current = new Audio(urls[index]);  // ← ref overwritten on each segment
```
`audioRef` holds only the *currently playing* segment. No pause state. No stop. When the next segment starts, the previous ref is gone.

### Architecture decision

**Centralize audio state in a `useAudioPlayer` hook lifted to `ChatWindow` level.**

Why centralized rather than per-message:
- Only one audio stream should play at a time — per-message refs cannot coordinate with each other or with auto-play
- Player controls need to be visible regardless of scroll position (user scrolls up while audio is playing)
- `ChatWindow` already owns both auto-play trigger (on query result) and the voice mode toggle — natural owner of playback state

The hook exposes `{ play, pause, resume, stop, isPlaying, isPaused }`. A persistent `AudioPlayerBar` component renders at the bottom of the chat header when `isPlaying || isPaused`.

### Task list

- [ ] **1.1** Create `frontend/hooks/useAudioPlayer.ts`
  - State: `isPlaying`, `isPaused`, `currentUrlIndex`, `urls[]`
  - Refs: `audioRef` (current `Audio` object), `urlsRef` (full URL list), `indexRef` (current index)
  - `play(urls: string[])` — stops any in-flight audio, sets urls, starts from index 0
  - `pause()` — calls `audioRef.current.pause()`, sets `isPaused=true`
  - `resume()` — calls `audioRef.current.play()`, sets `isPaused=false`
  - `stop()` — calls `audioRef.current.pause()`, resets all state
  - Internal `playNext(index)` — creates `new Audio(urls[index])`, stores in ref, wires `onended` → `playNext(index+1)`, `onerror` → `stop()`
  - Cleanup `useEffect` on unmount: calls `stop()`

- [ ] **1.2** Create `frontend/components/chat/AudioPlayerBar.tsx`
  - Props: `isPlaying`, `isPaused`, `onPause`, `onResume`, `onStop`
  - Renders only when `isPlaying || isPaused`
  - Shows: waveform/speaker icon, "Playing audio…" label, Pause/Resume button, Stop button
  - Positioned as a thin bar between chat header and messages (or sticky at header bottom)

- [ ] **1.3** Update `ChatWindow.tsx`
  - Replace `playVoiceSequence` local function + state with `useAudioPlayer()`
  - On query result with voice: call `player.play(result.voice_urls ?? [result.voice_url])`
  - Render `<AudioPlayerBar>` below the header, wired to player controls
  - Remove the manual `audioRef` in `MessageBubble` — the "Play audio" button on a message should call `player.play(urls)` via a prop or context

- [ ] **1.4** Update `MessageBubble.tsx`
  - Remove `audioRef`, `handlePlayVoice` logic
  - Accept `onPlayVoice?: (urls: string[]) => void` prop
  - Wire the "Play audio" button to `onPlayVoice`

- [ ] **1.5** Wire `onPlayVoice` from `ChatWindow` → `MessageBubble` via the messages map

---

## Bug 2 — New Conversation Reopens the Previous One

### What's broken

User clicks "New Conversation," goes to dashboard, selects a document — and gets loaded back into the existing conversation instead of a blank one.

### Root cause (exact code)

**`dashboard/page.tsx:14-24`**
```ts
const handleSelectDocument = useCallback(async (documentId: string) => {
  const existingConversation = conversations.find(conv => conv.document_id === documentId);
  if (existingConversation) {
    setSelection({ conversationId: existingConversation.id, documentId });  // ← forces old conversation
    router.push('/chat');
    return;
  }
  setSelection({ conversationId: null, documentId });
  router.push('/chat');
}, [conversations, router, setSelection]);
```

`conversations.find(...)` finds the first existing conversation for that document and loads it unconditionally. There is no way for the user to start a fresh conversation from the dashboard if one already exists for their chosen document.

Secondary issue — **`ThreePanelLayout.tsx:28`**:
```ts
if (documentId === activeDocumentId && activeConversationId) return;  // ← no-ops document clicks
```
If the user is already in a conversation and clicks the same document in the right panel, nothing happens. They cannot reset to a new conversation from within the chat page at all.

### Architecture decision

**Dashboard should be a pure document picker, never a conversation restorer.**

Restoring an existing conversation is the job of the `ConversationSidebar` (left panel) — the user clicks a past conversation there. The dashboard's purpose is to start something new. Mixing "resume" logic into the dashboard create an ambiguous UX: the user thinks they're starting fresh but get teleported into an old thread.

Fix: remove the `conversations.find` from `DashboardPage` entirely. Always set `conversationId: null`. The user can resume via sidebar.

Also add a "New conversation" reset path within the chat page itself so the user doesn't have to leave.

### Task list

- [ ] **2.1** Fix `frontend/app/(protected)/dashboard/page.tsx`
  - Remove `useConversations()` import and usage
  - Remove `conversations.find(...)` block
  - `handleSelectDocument` always does: `setSelection({ conversationId: null, documentId })` then `router.push('/chat')`

- [ ] **2.2** Fix `frontend/components/layout/ThreePanelLayout.tsx`
  - Remove the early-return guard on line 28: `if (documentId === activeDocumentId && activeConversationId) return;`
  - When user clicks same document again while in a conversation, clear `conversationId` and start fresh
  - Update `handleSelectDocument`: if `documentId === activeDocumentId`, call `setSelection({ conversationId: null, documentId })` explicitly (don't skip)

- [ ] **2.3** (Optional UX) Add a "New chat" icon button in `ChatWindow.tsx` header
  - Calls `onConversationReset?.()` prop (clears only `conversationId`, keeps `documentId`)
  - Allows user to start a new thread on the same document without going to dashboard

---

## Bug 3 — Cache Hit Ignores `voice_mode`

### What's broken

If the user asks a question in voice mode and the answer is cached (previously generated), no WAV file is produced and no audio plays. The cached badge appears but sound is silent.

### Root cause (exact code)

**`lambdas/query_lambda/handler.py:138-147`** (same pattern in `submit/handler.py:257-270`):
```python
if cached_answer:
    return {
        "answer":                  cached_answer,
        "cached":                  True,
        "voice_url":               None,   # ← hardcoded None, ignores voice_mode
        "voice_credits_remaining": _get_voice_credits(user_id),
        "path":                    "cache",
    }
```

`voice_mode` is read from the request body (line 99) and passed through the rest of the pipeline, but the cache-hit early return happens at line 138, before `voice_mode` is ever checked. TTS is only run in `_finalize_and_respond()` (line 422+), which is never reached on a cache hit.

Same structure exists in `submit/handler.py` for the synchronous cache path.

### Architecture decision

**Run TTS on cache hits when `voice_mode=True`; do not cache the voice URL.**

Why not cache the voice URL alongside the text answer:
- Voice URLs are pre-signed S3 URLs with a 24-hour expiry. Caching them in Redis with the same TTL as the text answer (1 hour) is safe but adds complexity for marginal gain — the WAV file only needs to be generated once per cache-hit request, not stored persistently.
- The text cache key is user+doc+query scoped. Voice output is deterministic on the same text input, so generating it on demand is cheap (one TTS call) and avoids managing a second TTL dimension.

Fix: extract the TTS step out of `_finalize_and_respond` into a standalone helper `_maybe_add_voice(answer, voice_mode, user_id)` and call it from both the cache-hit path and the normal finalize path.

### Task list

- [ ] **3.1** Refactor `lambdas/query_lambda/handler.py`
  - Extract the TTS block (lines ~431-525) into `_maybe_add_voice(answer: str, voice_mode: bool, user_id: str) -> tuple[str | None, list[str] | None]`
  - In the cache-hit block (lines 138-147), after confirming `cached_answer` exists:
    ```python
    voice_url, voice_urls = _maybe_add_voice(cached_answer, voice_mode, user_id)
    return {
        "answer":                  cached_answer,
        "cached":                  True,
        "voice_url":               voice_url,
        "voice_urls":              voice_urls,
        "voice_credits_remaining": _get_voice_credits(user_id),
        "path":                    "cache",
    }
    ```
  - In `_finalize_and_respond`, replace the inline TTS block with a call to `_maybe_add_voice`

- [ ] **3.2** Apply same fix to `lambdas/submit/handler.py`
  - The synchronous cache path (lines 257-270) has the same `"voice_url": None` hardcode
  - Import or duplicate `_maybe_add_voice` (or share via `shared_lambda`) and call it there

- [ ] **3.3** Verify voice credit accounting on cache+voice path
  - `consume_voice_credit` must be called before TTS, `refund_voice_credit` on failure — the extracted helper already handles this internally, so no extra work needed
  - Confirm `voice_credits_remaining` is fetched AFTER the consume call so the returned count is accurate

- [ ] **3.4** Test the three cases:
  - Cache hit, `voice_mode=False` → `voice_url: null`, no credit consumed
  - Cache hit, `voice_mode=True`, credits available → `voice_urls` populated, credit decremented
  - Cache hit, `voice_mode=True`, zero credits → `voice_url: null`, TTS skipped gracefully

---

---

## Bug 4 — General Knowledge Questions Return "Not Found" Instead of Fallback Answer

### What's broken

When the user asks a general knowledge question ("What is the capital of France?") while a document is loaded, the model replies with only "I could not find this information in your documents" — even though it knows the answer from its own training data.

### Root cause (exact code)

**`lambdas/query_lambda/handler.py:264` — RRF gate**

When the user has documents, the router is skipped entirely (Path B). The pipeline always retrieves. The check at line 264:
```python
if top_rrf_score < MIN_USEFUL_RRF_SCORE:   # 0.005
    ...
    answer = direct_answer(query, history)   # uses model knowledge
```
`MIN_USEFUL_RRF_SCORE = 0.005` is meant to catch pure irrelevant queries, but company policy documents are long — any query produces *some* BM25/vector match just from stop-word overlap. "Capital of France" against an employment policy document scores above 0.005 because words like "the", "of", "is" match. The threshold is never tripped, so `direct_answer()` is never called.

The query falls through to `generate_answer()` with irrelevant policy chunks injected as context.

**`lambdas/query_lambda/sarvam.py:201-217` — `_build_rag_prompt`**

```python
prompt = f"""You are a helpful assistant that answers questions \
based strictly on the provided document context.

Rules:
- Answer ONLY using information from the context chunks below
- If the answer is not in the context, say: \
"I could not find this information in your documents"   ← hard rule, no fallback
- Be concise and specific
...
```

The prompt explicitly forbids the model from using its own knowledge and gives it a single fallback: print the "not found" string. The model complies — it sees the policy chunks, finds nothing about France, and outputs the exact phrase.

### Why the RRF threshold alone isn't the fix

Raising `MIN_USEFUL_RRF_SCORE` would help some cases but is fragile:
- The right threshold is document-dependent — a dense tech manual has different score distributions than a 2-page policy
- A too-high threshold causes legitimate document questions to be answered from general knowledge instead of the user's doc — the opposite problem
- The model already knows whether the context is relevant; we just need to give it permission to say so and fall back

### Architecture decision

**Fix the prompt in `_build_rag_prompt` only. No second LLM call, no threshold tuning.**

Two alternative approaches rejected:

| Approach | Problem |
|----------|---------|
| Raise `MIN_USEFUL_RRF_SCORE` | Fragile — threshold is document-specific; legitimate doc questions can fall through |
| Detect "not found" reply → call `direct_answer()` as a second pass | Doubles token cost on every miss; adds 8–15s latency to already-slow path |

The model is the right place to make this judgment — it sees the chunks and knows whether they're relevant to the query. The prompt just needs to unlock the fallback path and mandate the disclosure format.

### Task list

- [ ] **4.1** Update `_build_rag_prompt` in `lambdas/query_lambda/sarvam.py`

  Change the "not found" rule from a dead-end to a two-step fallback:

  ```python
  # Old rules block (lines 205-210):
  Rules:
  - Answer ONLY using information from the context chunks below
  - If the answer is not in the context, say:
    "I could not find this information in your documents"

  # New rules block:
  Rules:
  - Prefer answering from the document context chunks below
  - If the context contains the answer, use it and cite the relevant chunk or page
  - If the context does NOT contain the answer, first state that clearly, then provide
    the answer from your own general knowledge using this exact format:
    "This was not found in your documents. Based on my knowledge: [your answer]"
  - Never fabricate document content — only attribute information to the document
    if it actually appears in the context chunks
  ```

- [ ] **4.2** Verify the format string survives Sarvam's think-tag stripping

  `_strip_think_tags` only removes `<think>...</think>` blocks — the new response format has no tags, so no change needed. Confirm by checking the stripped output starts with "This was not found" when context is irrelevant.

- [ ] **4.3** Update the `path` field returned to the frontend

  Currently all `generate_answer()` responses return `path="rag"`. For the fallback case, distinguish it so the frontend can show a different badge. Two options:
  - Option A (simpler): detect the "not found in documents" prefix in the answer string inside `_finish()` and rewrite `path` to `"rag_fallback"`
  - Option B (cleaner): have `generate_answer()` return a tuple `(answer, used_context: bool)` and let the handler set `path` accordingly

  Recommend Option A — minimal change, no signature break.

- [ ] **4.4** Add `"rag_fallback"` badge to `MessageBubble.tsx` `PATH_LABELS`

  ```ts
  // frontend/components/chat/MessageBubble.tsx
  rag_fallback: { label: 'General Knowledge', color: 'bg-orange-500/15 text-orange-400 border-orange-500/20' },
  ```

  This gives the user a clear visual cue that the answer came from the model's training data, not their document.

- [ ] **4.5** Test three cases:
  - Question clearly in the document → answer from doc, `path="rag"`, no disclaimer
  - Question clearly NOT in the document (capital of France) → disclaimer + correct answer, `path="rag_fallback"`
  - Question partially in document → model should cite what it found and note what it supplemented

---

## Implementation Order

| Priority | Item | Why |
|----------|------|-----|
| 1 | Bug 4 (general knowledge fallback) | Prompt-only backend change, zero risk, highest user-facing impact |
| 2 | Bug 2 (dashboard fix) | One-line frontend change, zero risk, immediate UX win |
| 3 | Bug 3 (cache+voice) | Backend only, self-contained, no frontend changes needed |
| 4 | Bug 1 (audio controls) | Largest change (new hook + component), but isolated to chat UI |
