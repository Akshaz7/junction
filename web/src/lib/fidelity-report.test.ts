import { afterEach, describe, expect, it } from 'vitest'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { phaseResults, savePhaseResult } from '../../e2e/fidelity-report'

const directories: string[] = []
afterEach(() => { for (const directory of directories.splice(0)) rmSync(directory, { recursive: true, force: true }) })

describe('fidelity phase reports across worker restarts', () => {
  it('retains failures, excludes other runs, and merges in manifest order', () => {
    const directory = mkdtempSync(join(tmpdir(), 'fidelity-report-'))
    directories.push(directory)
    const phases = [{ id: 'desktop-1' }, { id: 'desktop-2' }, { id: 'phone-1' }]
    const first = { id: 'desktop-1', device: 'desktop', phase: 1, status: 'fail', mismatch_percent: 2 }
    const last = { id: 'phone-1', device: 'phone', phase: 1, status: 'pass', mismatch_percent: 0 }
    savePhaseResult(directory, last)
    savePhaseResult(directory, first)
    savePhaseResult(directory, { id: 'unrelated', device: 'desktop', phase: 99, status: 'pass' })
    // No process-local accumulator: a fresh read after a worker restart keeps both.
    expect(phaseResults(directory, phases)).toEqual([first, last])
    expect(phaseResults(join(directory, 'next-run'), phases)).toEqual([])
    const second = { id: 'desktop-2', device: 'desktop', phase: 2, status: 'error', reason: 'Capture timed out' }
    savePhaseResult(directory, second)
    expect(phaseResults(directory, phases)).toEqual([first, second, last])
  })
})
