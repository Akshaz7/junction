import type { Answer } from './types'

export const STILL_READING_STATUS = 'Still reading the drawing…'
export const STILL_READING_RETRY_MS = 4000
export const STILL_READING_MAX_MS = 90_000

/** The server's reply while a document's data is still being built. */
export const isStillProcessing = (answer: Answer): boolean => /still being processed/i.test(answer.answer.text_md)

/** Ask again every few seconds while the document is still being read, then return the latest answer. */
export async function askUntilReadable(
  ask: () => Promise<Answer>,
  { onWait, cancelled = () => false, intervalMs = STILL_READING_RETRY_MS, maxMs = STILL_READING_MAX_MS, sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)) }:
    { onWait?: () => void; cancelled?: () => boolean; intervalMs?: number; maxMs?: number; sleep?: (ms: number) => Promise<void> } = {},
): Promise<Answer> {
  let answer = await ask()
  for (let waited = 0; isStillProcessing(answer) && waited + intervalMs <= maxMs && !cancelled(); waited += intervalMs) {
    onWait?.()
    await sleep(intervalMs)
    if (cancelled()) break
    answer = await ask()
  }
  return answer
}
