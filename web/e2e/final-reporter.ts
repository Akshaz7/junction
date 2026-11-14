import type { FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** Record actual outcomes, including skipped coverage, without making failures look green. */
export default class FinalReporter implements Reporter {
  private rows: object[] = []
  private run = process.env.E2E_RUN_ID ?? 'local'
  private root = resolve(fileURLToPath(new URL('../../results/final/E2E/', import.meta.url)), this.run)
  onTestEnd(test: TestCase, result: TestResult) {
    // Playwright body attachments otherwise disappear on successful runs when traces are discarded.
    const attachments = resolve(this.root, 'attachments', test.id.replace(/[^a-zA-Z0-9_-]/g, '-'))
    for (const attachment of result.attachments) {
      if (!attachment.body) continue
      mkdirSync(attachments, { recursive: true })
      const path = resolve(attachments, attachment.name.replace(/[^a-zA-Z0-9_.-]/g, '-'))
      writeFileSync(path, attachment.body)
      attachment.path = path
    }
    const owner = test.title.match(/\[(WEB|3D|ENGINE|SERVER|PROJECTS)\]/)?.[1] ?? 'WEB'
    const row = {
      title: test.titlePath().join(' > '), owner, status: result.status, duration_ms: result.duration,
      errors: result.errors.map((e) => e.message?.replace(/\u001b\[[0-9;]*m/g, '')),
      annotations: test.annotations,
      attachments: result.attachments.map(({ name, path, contentType }) => ({ name, path, contentType })),
    }
    this.rows.push(row)
    mkdirSync(this.root, { recursive: true })
    writeFileSync(resolve(this.root, 'tests.json'), JSON.stringify(this.rows, null, 2) + '\n')
    if (result.status === 'failed' || result.status === 'timedOut') {
      const screenshot = result.attachments.some((a) => a.contentType.startsWith('image/'))
      appendFileSync('/Users/akshatthapa/Workspace/junction/handoff/F-E2E.md',
        `FAIL F-E2E (${new Date().toISOString()}, ${this.run}) owner ${owner}: ${test.title}; ${row.errors[0]?.split('\n').filter(Boolean).slice(0, 3).join(' ').slice(0, 350)}; ${screenshot ? 'screenshot + trace' : 'trace (no screenshot: browser did not open, or API-only check)'}: results/final/E2E/${this.run}/artifacts/\n`)
    }
  }
  onEnd(result: FullResult) {
    mkdirSync(this.root, { recursive: true })
    writeFileSync(resolve(this.root, 'summary.json'), JSON.stringify({
      run: this.run, base_url: process.env.E2E_BASE ?? 'http://localhost:5173', ...result,
      counts: this.rows.reduce<Record<string, number>>((counts, row) => {
        const status = (row as { status: string }).status
        counts[status] = (counts[status] ?? 0) + 1
        return counts
      }, {}),
    }, null, 2) + '\n')
  }
}
