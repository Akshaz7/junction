import type { Response } from '@playwright/test'
import type { Answer } from '../src/lib/types'

/** Read the answer actually returned by the backend; fixture counts can change. */
export async function streamedAnswer(response: Response): Promise<Answer> {
  if (!response.ok()) throw new Error(`Question failed: HTTP ${response.status()}`)
  const stream = await response.text()
  for (const event of stream.replace(/\r\n/g, '\n').split('\n\n')) {
    const lines = event.split('\n')
    if (lines.find((line) => line.startsWith('event:'))?.slice(6).trim() !== 'answer') continue
    return JSON.parse(lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')) as Answer
  }
  throw new Error('Question stream ended without an answer event')
}
