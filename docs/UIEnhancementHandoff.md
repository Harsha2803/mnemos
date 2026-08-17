# Mnemos UI Enhancement Handoff

Reviewed: 2026-08-17

Scope reviewed:
- Product docs: `README.md`, `TRACKER.md`, `docs/DesignSystem.md`, `docs/ADAPTATION.md`, `docs/Roadmap.md`
- Frontend shell and routes: overview, chat, knowledge, sources, sign-in
- Main UI components: app shell, sidebar, inspector, composer, message bubbles, SQL panel, document upload/list, source registration/browser/activity feed, auth/status primitives

## Current UI Baseline

The app already has a strong foundation:
- Three-column shell with resizable sidebar and inspector.
- Semantic design tokens, dark mode, visible focus, 44px hit targets, reduced-motion support.
- Functional chat with SSE streaming, stop generation, citations as real buttons, conversation rename/delete.
- Knowledge upload and document list.
- Sources workflow with register, browse, select, ingest, live activity, progress, retry/stuck/error state.
- Sign-in and auth boundary that preserve destination and avoid leaking tenant-specific failure details.

The best enhancements are therefore not generic visual polish. They should make Mnemos more legible as a governed AI workspace: what it can see, what evidence it used, what is processing, and whether the answer can be trusted.

## Priority Enhancements

### P0. Context Inspector Upgrade

Value:
- The inspector is the product's differentiator. Today it only shows the clicked citation passage.
- Upgrading it makes the README claim visible in the product instead of only in docs.

Suggested UI:
- Add inspector sections or tabs:
  - `Source`: quoted passage, page/character range, score, document title.
  - `Evidence`: all citations for the selected assistant message, not only the clicked marker.
  - `Bundle`: admitted items, excluded items, token budget, retrieval operators, degradation events when backend support lands.
  - `SQL`: generated SQL, authorized/denied tables, execution metadata for NL2SQL answers.
- Let clicking an assistant message select the whole answer; clicking a citation selects a specific evidence item.
- Add previous/next citation controls in the inspector for keyboard-friendly review.

Implementation notes:
- Expand `InspectorSelection` from citation-only to a union such as `message`, `citation`, `sql`, `bundle`.
- Keep the right panel permanent on desktop and sheet-based on smaller viewports, matching `AppShell`.
- Backend may need document title/source fields in `CitationResponse`.

### P0. Citation Preview And Evidence Navigation

Value:
- Citations are currently clickable markers, but users cannot preview what they mean without moving to the inspector.
- Fast preview increases trust without breaking reading flow.

Suggested UI:
- On hover/focus of `[n]`, show a small popover with:
  - quoted excerpt
  - page/character range
  - relevance score if present
  - source title if backend provides it
- Add a citation list below assistant answers when there are 2+ sources, using compact chips or rows.
- Highlight the selected citation marker and matching inspector passage.

Implementation notes:
- Use Radix popover or tooltip only if already acceptable for the project; otherwise a small custom accessible disclosure may be needed.
- Preserve the citation marker as a real button.

### P1. Operational Overview Dashboard

Value:
- The current overview is mostly text plus system readiness.
- Users need a scanning surface that answers: "Is Mnemos ready? What knowledge exists? What is still processing? What can I ask now?"

Suggested UI:
- Replace the sparse overview with a dense operational dashboard:
  - System readiness summary.
  - Knowledge count: documents, passages, recent uploads.
  - Sources count: registered sources, enabled/disabled, recent ingest state.
  - Recent ingestion activity.
  - Recent conversations.
  - Quick actions: new chat, upload documents, connect source.
- Keep it utilitarian, not a marketing hero.

Implementation notes:
- Reuse `SystemStatus`, `DocumentList` summary data, connector job data, and chat session data.
- Avoid nested cards. Use full-width sections and compact repeated rows.

### P1. Knowledge Library Table Upgrade

Value:
- Documents are listed, but the list does not yet support real library management.
- A user with more than a handful of documents needs search, filters, status, and provenance.

Suggested UI:
- Replace or supplement the simple list with a responsive table/list hybrid.
- Add:
  - search by title
  - filter by status
  - sort by created date, title, size, passage count
  - semantic status chips
  - source kind/source URI when available
  - superseded badge/state
  - row action: "Ask about this"
  - row action: "View passages" when backend exposes chunks
- Show empty, loading, failed, and partially indexed states distinctly.

Implementation notes:
- Start in `DocumentList.tsx` and `knowledge/page.tsx`.
- Backend `DocumentResponse` already has title, media type, byte size, status, superseded_by, chunk_count, created_at.
- Source fields may require schema additions.

### P1. Upload Queue With Per-File Feedback

Value:
- Multi-file upload exists, but pending state collapses the batch into one skeleton.
- Per-file feedback helps users understand which files worked and which need attention.

Suggested UI:
- Show a queue immediately after file selection/drop:
  - file name
  - size
  - state: validating, uploading, extracting, chunking, embedding, done, failed
  - retry failed upload
  - remove queued file before upload starts
- Show a batch summary after completion.
- Keep the current immediate max-size validation.

Implementation notes:
- `UploadControl.tsx` can maintain per-file local state before backend job support is available.
- Once manual uploads move to async jobs, reuse `EventFeed` stage/status patterns.

### P1. Sources Workflow Refinement

Value:
- Sources are powerful but the screen is form-heavy.
- Better scanning and validation would reduce setup mistakes.

Suggested UI:
- Split source registration into provider-specific panels or a segmented provider selector.
- Show provider icons, enabled/disabled state, created date, and last activity in `SourceList`.
- Add inline validation:
  - slug format preview
  - required field hints by source kind
  - URL count and invalid URL lines for HTTP
- Add browse toolbar:
  - search/filter items
  - select all visible
  - file type filters
  - modified date and size columns
- Add "already ingested" state once backend can report it.

Implementation notes:
- Touch `RegisterSourceForm.tsx`, `SourceList.tsx`, `ItemBrowser.tsx`, and `sources/page.tsx`.
- `ItemResponse.modified_at` already exists but is not displayed.
- `SourceResponse.is_enabled` and `created_at` already exist but are not displayed.

### P1. Ingestion Activity Timeline

Value:
- The current feed shows status, attempts, progress, and error details.
- The backend now returns event history, which can become a much more useful diagnostic UI.

Suggested UI:
- Make each feed row expandable.
- Expanded row shows:
  - queued -> running -> succeeded/failed/stuck timeline
  - timestamps
  - owner id when relevant
  - heartbeat/lease details for stuck jobs
  - retry attempts
  - error detail
- Add filters for active, failed/stuck, succeeded.
- Add "copy job id" as an icon button for debugging.

Implementation notes:
- `IngestJobResponse.events`, `heartbeat_at`, `lease_expires_at`, `started_at`, `finished_at`, and `owner_id` already exist in the generated schema.
- Extend `FeedJob` or pass full job records into `EventFeed`.

### P1. SQL Result Experience Upgrade

Value:
- `SqlPanel` is already valuable, especially refusals.
- Users need to understand query safety, truncation, and result shape without reading raw SQL first.

Suggested UI:
- Add a compact metadata strip:
  - verdict
  - attempt count
  - duration
  - row count
  - truncated state
  - authorized tables
  - denied tables
- Add SQL collapse/expand with "copy SQL".
- Add table affordances:
  - sticky header
  - horizontal scroll hint
  - copy cell/row/table
  - empty result state
- For denied queries, emphasize what was blocked and why, then show SQL second.

Implementation notes:
- `Nl2SqlResult` already exposes most metadata in `stream.ts`.
- `SqlPanel.tsx` is the main component.

### P1. Chat Transcript Usability

Value:
- The chat works, but long sessions need navigation and answer controls.

Suggested UI:
- Add message actions:
  - copy answer
  - retry/regenerate
  - select/open in inspector
  - jump to citations
- Add date separators or session timestamps.
- Preserve scroll intent: auto-scroll only when the user is already near the bottom.
- Add an error state that distinguishes aborted generation from backend failure.

Implementation notes:
- Touch `MessageList.tsx`, `MessageBubble.tsx`, and chat page streaming state.
- Be careful not to animate or remount streaming bubbles unnecessarily.

### P2. Sidebar Improvements

Value:
- The sidebar is functional and accessible, but can become more useful for repeated work.

Suggested UI:
- Add conversation search/filter.
- Group conversations by recency: Today, Yesterday, Previous 7 days, Older.
- Add unread/processing indicators if background work becomes relevant.
- Persist sidebar and inspector widths/pinned state per browser.
- Add "collapse to icon rail" desktop variant instead of only width zero.

Implementation notes:
- `AppShell` currently stores widths/pinned state in React state only.
- Use localStorage carefully to avoid hydration mismatch.

### P2. Account And Permissions Visibility

Value:
- Enterprise users need to understand who they are and what they can access.
- The API already returns permissions and tags.

Suggested UI:
- Make account footer expandable or clickable.
- Show:
  - display name/email/org
  - permissions count/list
  - reachable tags
  - session id copy action for support
- Add disabled nav/actions when permissions become enforced in UI.

Implementation notes:
- `MeResponse.permissions` and `tags` already exist.
- Keep hiding controls as courtesy only; backend remains the enforcement layer.

### P2. Empty States With Product Actions

Value:
- Empty states are accessible and consistent, but some can better guide the next action.

Suggested UI:
- Chat empty state: example prompts for plain chat, documents, and data.
- Knowledge empty state: upload action plus connect source action.
- Sources empty state: register source action with the common local fixture path in dev.
- Inspector empty state: show what can be inspected today and what unlocks after context layer lands.

Implementation notes:
- Keep copy concise. Avoid in-app explanation of implementation details.

### P2. Responsive/Mobile Polish

Value:
- Shell sheets exist, but dense tables and composer controls need mobile-specific review.

Suggested UI:
- Convert item browser and SQL results into stacked rows on narrow screens.
- Ensure composer controls wrap without crowding.
- Add sticky action bars for selected source items.
- Test inspector sheet with long passages and table content.

Implementation notes:
- Add Playwright viewport coverage for chat, sources, and SQL panel.

### P2. Visual Density And Hierarchy Pass

Value:
- The design system is strong, but several pages use large text and explanatory paragraphs.
- As the app becomes more operational, pages should scan faster.

Suggested UI:
- Reduce repeated descriptive paragraphs on pages once workflows are self-evident.
- Use tighter section headers, metadata rows, and compact status labels.
- Avoid adding decorative cards; use full-width bands or grouped lists.
- Keep accent color for interactive affordances and state only.

Implementation notes:
- Audit `OverviewPage`, `KnowledgePage`, and `SourcesPage` first.

## Suggested Implementation Order

1. Expand inspector selection model and add answer-level evidence view.
2. Upgrade overview into an operational dashboard.
3. Improve knowledge library search/filter/status.
4. Expand ingestion activity rows into timelines.
5. Polish SQL panel metadata and copy affordances.
6. Add source/item browser search, select-all, and modified-date display.
7. Persist shell widths/pinned state and add conversation search.

## Design Constraints To Preserve

- Keep the three-column shell as the desktop information architecture.
- Use existing tokens and components before adding new styling patterns.
- Keep citations as buttons and interactive controls keyboard reachable.
- Do not add a second chat/ask surface.
- Do not make the overview or any product screen feel like a marketing landing page.
- Do not hard-code color literals outside `globals.css`.
- Pair status color with icon or plain text.
- Keep destructive actions named and confirmed.
- Regenerate `frontend/src/lib/api/schema.ts` from OpenAPI when API contracts change. Do not hand-edit it.

## Useful Files For An Implementing Agent

- `TRACKER.md`: start here for current milestone and constraints.
- `docs/DesignSystem.md`: design system rules and rationale.
- `frontend/src/components/shell/AppShell.tsx`: layout and responsive shell behavior.
- `frontend/src/components/shell/InspectorContent.tsx`: current inspector.
- `frontend/src/lib/inspector/SelectionProvider.tsx`: selection model to expand.
- `frontend/src/components/chat/MessageBubble.tsx`: answer rendering, citations, SQL panel slot.
- `frontend/src/components/chat/SqlPanel.tsx`: NL2SQL result/refusal UI.
- `frontend/src/components/knowledge/DocumentList.tsx`: document library.
- `frontend/src/components/knowledge/UploadControl.tsx`: upload state.
- `frontend/src/components/connectors/EventFeed.tsx`: ingestion activity.
- `frontend/src/components/connectors/ItemBrowser.tsx`: source item selection.
- `frontend/src/components/connectors/RegisterSourceForm.tsx`: source setup.
