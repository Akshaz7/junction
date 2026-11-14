# WEB4: row W-26 (Codex). Export an answer as a site report
Scope: new files web/src/components/answer-export.tsx/.css and web/src/lib/answer-export.ts (+ tests). Do not edit other components; expose an <ExportAnswerButton answer docs chatId/> that the LEAD mounts.
Builders need to send proof to others. Export one answer (or a whole chat) as a clean, printable report:
- the question, the answer text, the numbered citations
- the drawing crop with the numbered boxes drawn on it, rendered on a canvas from the page image and the evidence boxes
- the doc title, licence/credit and cost
- generated date
Output: print-ready HTML via window.print with a print stylesheet, plus "Copy as Markdown". No new server endpoints. Use the existing APIs for page images. App tokens, works on a phone.
Done test: tsc + vitest with unit tests for the report model and the Markdown output.
Do not commit. Append a RESULT: line.
RESULT: W-26 passed: `cd web && npx tsc --noEmit` and `npx vitest run` (45 files, 268 tests; 15 new export tests). Added only web/src/components/answer-export.tsx/.css, answer-export.test.ts and web/src/lib/answer-export.ts/.test.ts; mount named ExportAnswerButton with answer, docs, chatId (optional demo). Includes single-answer/whole-chat report preview, canvas crops with original evidence labels, printable standalone HTML, Markdown copy/fallback, source credits/licences, costs, generated date and missing-image notices; no commit.
