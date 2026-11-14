# W-15 wiring for WEB (apply in the attempt after W-18 attempt 5)

1. App.tsx (exact):
```tsx
import { OverviewScreen } from './components/overview-screen'
{view === 'overview' && <OverviewScreen docs={docs} />}   // beside AccuracyScreen
add `view !== 'overview' &&` to the PlaceholderPage condition
```
2. chat-screen.tsx: handle hash `#/chat?chat=<id>` (GET /api/chats/{id}, restore that chat's question/answer history and chatId) and `#/chat?question=<encoded>` (prefill the composer, don't send), on load and on hashchange.
3. Done test: e2e/overview.spec.ts (2 tests). LEAD ran it at 05:30 with only (1): both fail exactly at the chat deep-link step (saved chat 'How many doors are there?' not shown; composer value '' instead of 'How many windows are there?').
