import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { recordQuestion, speakAnswer, stripSpeechMarkdown, VOICE_UNAVAILABLE } from './voice'

class DeviceUtterance {
  lang = ''
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(readonly text: string) {}
}
class TestAudio {
  hidden = false
  dataset: Record<string, string> = {}
  src = ''
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  play = vi.fn().mockResolvedValue(undefined)
  pause = vi.fn()
  removeAttribute = vi.fn()
  load = vi.fn()
  remove = vi.fn()
}
let audio: TestAudio
let device: { speak: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn> }
let transport: ReturnType<typeof vi.fn<typeof fetch>>
let revoke: ReturnType<typeof vi.fn<(url: string) => void>>

beforeEach(() => {
  audio = new TestAudio()
  device = { speak: vi.fn(), cancel: vi.fn() }
  transport = vi.fn<typeof fetch>()
  revoke = vi.fn()
  vi.stubGlobal('fetch', transport)
  vi.stubGlobal('speechSynthesis', device)
  vi.stubGlobal('SpeechSynthesisUtterance', DeviceUtterance)
  vi.stubGlobal('document', { createElement: vi.fn(() => audio), body: { append: vi.fn() } })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:spoken-answer')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(revoke)
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('spoken answers', () => {
  it('reads facts without markdown, numeric citation badges, links, or headings', () => {
    expect(stripSpeechMarkdown('## **11 windows** [1].\n- See [the plan](https://example.com) [2, 3].'))
      .toBe('11 windows. See the plan.')
    expect(stripSpeechMarkdown('Use `width_m` and *height*. [4–6]')).toBe('Use width_m and height.')
  })

  it('posts plain text, plays the real audio bytes and revokes the URL on completion', async () => {
    transport.mockResolvedValue(new Response(new Blob(['mpeg bytes']), { headers: { 'Content-Type': 'audio/mpeg' } }))
    const control = await speakAnswer('There are **11 windows**. [1]')
    expect(transport).toHaveBeenCalledWith('/api/tts', expect.objectContaining({ method: 'POST', body: JSON.stringify({ text: 'There are 11 windows.' }) }))
    expect(control.status).toBe('playing')
    expect(audio.play).toHaveBeenCalledOnce()
    expect(device.speak).not.toHaveBeenCalled()
    expect(revoke).not.toHaveBeenCalled()
    audio.onended!()
    await control.finished
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:spoken-answer')
    expect(audio.remove).toHaveBeenCalledOnce()
  })

  it.each(['missing-key', 'server-error', 'network-error', 'empty-audio', 'playback-error'])(
    'uses device speech on %s', async (failure) => {
      if (failure === 'missing-key') transport.mockResolvedValue(Response.json({ fallback: 'device' }))
      if (failure === 'server-error') transport.mockResolvedValue(new Response('', { status: 503 }))
      if (failure === 'network-error') transport.mockRejectedValue(new TypeError('offline'))
      if (failure === 'empty-audio') transport.mockResolvedValue(new Response('', { headers: { 'Content-Type': 'audio/mpeg' } }))
      if (failure === 'playback-error') {
        transport.mockResolvedValue(new Response('mpeg', { headers: { 'Content-Type': 'audio/mpeg' } }))
        audio.play.mockRejectedValue(new Error('Playback failed'))
      }
      const control = await speakAnswer('**11 windows** [1]')
      expect(control.status).toBe('fallback')
      expect(device.speak).toHaveBeenCalledOnce()
      const utterance = device.speak.mock.calls[0][0] as DeviceUtterance
      expect(utterance.text).toBe('11 windows')
      utterance.onend!()
      await control.finished
    },
  )

  it('stops audio once and releases its resources', async () => {
    transport.mockResolvedValue(new Response('mpeg', { headers: { 'Content-Type': 'audio/mpeg' } }))
    const control = await speakAnswer('Windows')
    control.stop(); control.stop()
    await control.finished
    expect(audio.pause).toHaveBeenCalledOnce()
    expect(audio.removeAttribute).toHaveBeenCalledWith('src')
    expect(revoke).toHaveBeenCalledOnce()
  })

  it('cancels the device voice when stopped', async () => {
    transport.mockResolvedValue(Response.json({ fallback: 'device' }))
    const control = await speakAnswer('Windows')
    control.stop(); control.stop()
    await control.finished
    expect(device.cancel).toHaveBeenCalledOnce()
  })

  it('does not cancel another voice after its own utterance has finished', async () => {
    transport.mockResolvedValue(Response.json({ fallback: 'device' }))
    const control = await speakAnswer('Windows')
    const utterance = device.speak.mock.calls[0][0] as DeviceUtterance
    utterance.onend!()
    await control.finished
    control.stop()
    expect(device.cancel).not.toHaveBeenCalled()
  })

  it('starts device fallback once when an audio error also rejects play', async () => {
    transport.mockResolvedValue(new Response('mpeg', { headers: { 'Content-Type': 'audio/mpeg' } }))
    audio.play.mockImplementation(async () => {
      audio.onerror!()
      throw new Error('Unsupported audio')
    })
    const control = await speakAnswer('Windows')
    expect(control.status).toBe('fallback')
    expect(device.speak).toHaveBeenCalledOnce()
    control.stop()
  })

  it('updates the fallback hint if audio fails after playback has started', async () => {
    transport.mockResolvedValue(new Response('mpeg', { headers: { 'Content-Type': 'audio/mpeg' } }))
    const onStatus = vi.fn()
    const control = await speakAnswer('Windows', { onStatus })
    expect(onStatus).toHaveBeenLastCalledWith('playing')
    audio.onerror!()
    expect(onStatus).toHaveBeenLastCalledWith('fallback')
    expect(control.status).toBe('fallback')
    control.stop()
  })

  it('aborts a pending request without starting fallback speech', async () => {
    transport.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init!.signal!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    }))
    const signal = new AbortController()
    const pending = speakAnswer('Windows', { signal: signal.signal })
    signal.abort()
    const control = await pending
    await control.finished
    expect(device.speak).not.toHaveBeenCalled()
    expect(audio.play).not.toHaveBeenCalled()
  })

  it('reports unavailable device speech and empty answers without hanging', async () => {
    vi.stubGlobal('speechSynthesis', undefined)
    transport.mockResolvedValue(Response.json({ fallback: 'device' }))
    const control = await speakAnswer('Windows')
    expect(control.status).toBe('error')
    await control.finished
    transport.mockClear()
    const empty = await speakAnswer('** [1] **')
    expect(empty.status).toBe('error')
    await empty.finished
    expect(transport).not.toHaveBeenCalled()
  })
})

class TestRecognition {
  static latest: TestRecognition
  lang = ''; continuous = true; interimResults = true
  onresult: ((event: { resultIndex: number; results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null = null
  onerror: (() => void) | null = null
  onend: (() => void) | null = null
  start = vi.fn()
  stop = vi.fn(() => this.onend?.())
  abort = vi.fn()
  constructor() { TestRecognition.latest = this }
}
class TestRecorder {
  static latest: TestRecorder
  static isTypeSupported = () => true
  state = 'inactive'
  mimeType = 'audio/webm;codecs=opus'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() { TestRecorder.latest = this }
  start() { this.state = 'recording' }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['recorded speech'], { type: this.mimeType }) })
    this.onstop?.()
  }
}
const handlers = () => ({ onText: vi.fn(), onState: vi.fn(), onError: vi.fn() })

describe('question microphone', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('window', {})
    vi.stubGlobal('navigator', {})
    vi.stubGlobal('MediaRecorder', undefined)
  })

  it('shows an actionable message when neither recording nor recognition is available', () => {
    const callbacks = handlers()
    recordQuestion(callbacks)
    expect(callbacks.onError).toHaveBeenCalledWith(VOICE_UNAVAILABLE)
    expect(callbacks.onText).not.toHaveBeenCalled()
    expect(callbacks.onState).toHaveBeenLastCalledWith('idle')
  })

  it('uses prefixed device recognition, emits only final text, and cancels cleanly', () => {
    vi.stubGlobal('window', { webkitSpeechRecognition: TestRecognition })
    const callbacks = handlers()
    const control = recordQuestion(callbacks)
    const recognition = TestRecognition.latest
    expect(recognition.start).toHaveBeenCalledOnce()
    recognition.onresult!({ resultIndex: 0, results: [{ isFinal: false, 0: { transcript: 'unfinished' } }] })
    expect(callbacks.onText).not.toHaveBeenCalled()
    recognition.onresult!({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: ' Count the doors. ' } }] })
    expect(callbacks.onText).toHaveBeenCalledExactlyOnceWith('Count the doors.')
    control.cancel()
    expect(recognition.abort).toHaveBeenCalledOnce()
    expect(recognition.onresult).toBeNull()
  })

  it('uploads recorded audio as multipart file and returns text without submitting a chat', async () => {
    const stopTrack = vi.fn()
    vi.stubGlobal('MediaRecorder', TestRecorder)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] }) } })
    transport.mockResolvedValue(Response.json({ text: ' How many doors? ', intent: 'ask' }))
    const callbacks = handlers()
    const control = recordQuestion(callbacks)
    await vi.waitFor(() => expect(callbacks.onState).toHaveBeenCalledWith('recording'))
    control.stop()
    await vi.waitFor(() => expect(callbacks.onText).toHaveBeenCalledWith('How many doors?'))
    expect(transport).toHaveBeenCalledExactlyOnceWith('/api/speech-intent', expect.objectContaining({ method: 'POST', body: expect.any(FormData) }))
    const file = (transport.mock.calls[0][1]!.body as FormData).get('file') as File
    expect(file.type).toBe('audio/webm')
    expect(await file.text()).toBe('recorded speech')
    expect(stopTrack).toHaveBeenCalledOnce()
    expect(callbacks.onState).toHaveBeenLastCalledWith('idle')
  })

  it.each(['show me all the windows', 'remove window W3', 'undo'])('passes the scene command "%s" through device transcription', (text) => {
    vi.stubGlobal('window', { webkitSpeechRecognition: TestRecognition })
    const callbacks = handlers()
    const control = recordQuestion(callbacks)
    TestRecognition.latest.onresult!({ resultIndex: 0, results: [{ isFinal: true, 0: { transcript: text } }] })
    expect(callbacks.onText).toHaveBeenCalledExactlyOnceWith(text)
    control.cancel()
  })

  it('falls back to browser recognition after a missing speech key and stops after 30 seconds', async () => {
    vi.stubGlobal('window', { SpeechRecognition: TestRecognition })
    vi.stubGlobal('MediaRecorder', TestRecorder)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) } })
    transport.mockResolvedValue(Response.json({ fallback: 'device' }))
    const callbacks = handlers()
    const control = recordQuestion(callbacks)
    await vi.waitFor(() => expect(callbacks.onState).toHaveBeenCalledWith('recording'))
    control.stop()
    await vi.waitFor(() => expect(callbacks.onState).toHaveBeenCalledWith('recognizing'))
    expect(TestRecognition.latest.start).toHaveBeenCalledOnce()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(TestRecognition.latest.stop).toHaveBeenCalledOnce()
    expect(callbacks.onState).toHaveBeenLastCalledWith('idle')
    expect(callbacks.onText).not.toHaveBeenCalled()
  })

  it('releases a microphone granted after cancellation without recording or uploading', async () => {
    const stopTrack = vi.fn()
    let grant!: (stream: { getTracks: () => { stop: typeof stopTrack }[] }) => void
    vi.stubGlobal('MediaRecorder', TestRecorder)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: () => new Promise((resolve) => { grant = resolve }) } })
    const callbacks = handlers()
    const control = recordQuestion(callbacks)
    control.cancel()
    grant({ getTracks: () => [{ stop: stopTrack }] })
    await Promise.resolve()
    expect(stopTrack).toHaveBeenCalledOnce()
    expect(callbacks.onState).not.toHaveBeenCalledWith('recording')
    expect(callbacks.onText).not.toHaveBeenCalled()
    expect(transport).not.toHaveBeenCalled()
  })
})
