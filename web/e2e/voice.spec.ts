import { expect, test } from '@playwright/test'

// LEAD wires #/voice-test after W-18; see handoff/WEB2.md for the exact six lines.
test.use({ launchOptions: {
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  args: ['--autoplay-policy=no-user-gesture-required'],
} })

test('with a configured key the real TTS endpoint returns audio and plays it', async ({ page }) => {
  test.setTimeout(45_000)
  await page.goto('/#/voice-test')
  await page.evaluate(() => {
    document.addEventListener('play', (event) => {
      if (event.target instanceof HTMLAudioElement) document.documentElement.dataset.voicePlayed = 'true'
    }, true)
  })
  const responsePromise = page.waitForResponse((response) => response.url().endsWith('/api/tts') && response.request().method() === 'POST', { timeout: 35_000 })
  await page.getByRole('button', { name: 'Play spoken answer', exact: true }).click()
  const response = await responsePromise
  expect(response.request().postDataJSON()).toEqual({ text: 'There are 11 windows.' })
  expect(response.status()).toBe(200)
  // A missing key is a failure here: this test must run against the real configured backend.
  expect(response.headers()['content-type']).toContain('audio/mpeg')
  await expect(page.locator('html')).toHaveAttribute('data-voice-played', 'true', { timeout: 10_000 })
})

test('without a key the device voice speaks the answer and Stop cancels it', async ({ page }) => {
  await page.addInitScript(() => {
    const calls: string[] = []
    let stops = 0
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
      speak(utterance: SpeechSynthesisUtterance) {
        calls.push(utterance.text)
        document.documentElement.dataset.spokenAnswers = JSON.stringify(calls)
      },
      cancel() { document.documentElement.dataset.voiceStops = String(++stops) },
    } })
  })
  // The sole API mock simulates the documented missing-key response.
  await page.route('**/api/tts', (route) => route.fulfill({ json: { fallback: 'device' } }))
  await page.goto('/#/voice-test')
  await page.getByRole('button', { name: 'Play spoken answer', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-spoken-answers', JSON.stringify(['There are 11 windows.']))
  await expect(page.getByText('device voice', { exact: true })).toBeVisible()
  const stop = page.getByRole('button', { name: 'Stop', exact: true })
  await expect(stop).toHaveAttribute('aria-pressed', 'true')
  await stop.click()
  await expect(page.locator('html')).toHaveAttribute('data-voice-stops', '1')
  await expect(page.getByRole('button', { name: 'Play spoken answer', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('textbox')).toHaveValue('')
})
