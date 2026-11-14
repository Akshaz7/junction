import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

export type PhaseResult = { id: string; device: string; phase: number; status: string; reason?: string; [key: string]: unknown }

/** Playwright clears outputDir once per run, while workers restart after failures.
 * Store one record per phase there so restarted workers cannot erase earlier results
 * or reuse results from a previous run. Keep the public report in manifest order. */
export function phaseResults(directory: string, phases: { id: string }[]) {
  return phases.flatMap(({ id }) => {
    const path = resolve(directory, `${id}.json`)
    return existsSync(path) ? [JSON.parse(readFileSync(path, 'utf8')) as PhaseResult] : []
  })
}

export function savePhaseResult(directory: string, result: PhaseResult) {
  mkdirSync(directory, { recursive: true })
  writeFileSync(resolve(directory, `${result.id}.json`), JSON.stringify(result, null, 2) + '\n')
}
