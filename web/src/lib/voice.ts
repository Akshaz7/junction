export type SpeechStatus = 'playing' | 'fallback' | 'error'
export type SpeechController = {
  readonly status: SpeechStatus
  /** Resolves on completion, cancellation, or a playback error. */
  finished: Promise<void>
  stop: () => void
}

export function stripSpeechMarkdown(text: string): string {
  return text
    .replace(/!?\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\[\d+(?:\s*[,–-]\s*\d+)*\]/g, '')
    .replace(/\*\*|__|`+/g, '')
    .replace(/(^|\s)[*_]([^*_]+)[*_](?=\s|[.,!?]|$)/g, '$1$2')
    .replace(/^\s*(?:#{1,6}\s+|[-*>]\s+)/gm, '')
    .replace(/\s+([.,!?;:])/g, '$1')
    .replace(/\s+/g, ' ').trim()
}

/** Uses the real speech endpoint; missing providers and playback failures use device speech. */
export async function speakAnswer(text: string, options: {
  signal?: AbortSignal; onStatus?: (status: SpeechStatus) => void
} = {}): Promise<SpeechController> {
  const plainText = stripSpeechMarkdown(text)
  const request = new AbortController()
  let status: SpeechStatus = 'error'
  let stopped = false
  let completed = false
  let deviceStarted = false
  let audio: HTMLAudioElement | undefined
  let objectUrl: string | undefined
  let utterance: SpeechSynthesisUtterance | undefined
  let settle!: () => void
  const finished = new Promise<void>((resolve) => { settle = resolve })
  function updateStatus(next: SpeechStatus) { status = next; options.onStatus?.(next) }
  function releaseAudio() {
    if (audio) {
      audio.onended = null
      audio.onerror = null
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
      audio.remove()
      audio = undefined
    }
    if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = undefined }
  }
  function finish() {
    if (completed) return
    completed = true
    options.signal?.removeEventListener('abort', stop)
    releaseAudio()
    if (utterance) { utterance.onend = null; utterance.onerror = null; utterance = undefined }
    settle()
  }
  function stop() {
    if (stopped || completed) return
    stopped = true
    request.abort()
    if (utterance) globalThis.speechSynthesis?.cancel()
    finish()
  }
  const controller: SpeechController = { get status() { return status }, finished, stop }
  function deviceSpeech() {
    if (stopped || completed || deviceStarted) return
    deviceStarted = true
    releaseAudio()
    if (!globalThis.speechSynthesis || !globalThis.SpeechSynthesisUtterance) { updateStatus('error'); finish(); return }
    try {
      utterance = new SpeechSynthesisUtterance(plainText)
      utterance.lang = 'en-US'
      utterance.onend = finish
      utterance.onerror = () => { updateStatus('error'); finish() }
      updateStatus('fallback')
      speechSynthesis.speak(utterance)
    } catch { updateStatus('error'); finish() }
  }
  options.signal?.addEventListener('abort', stop, { once: true })
  if (options.signal?.aborted || !plainText) { stop(); return controller }
  try {
    const response = await fetch('/api/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: plainText }),
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]),
    })
    if (!response.ok || !response.headers.get('content-type')?.toLowerCase().startsWith('audio/mpeg')) {
      deviceSpeech()
      return controller
    }
    const blob = await response.blob()
    if (stopped) return controller
    if (!blob.size) { deviceSpeech(); return controller }
    objectUrl = URL.createObjectURL(blob)
    audio = document.createElement('audio')
    audio.hidden = true
    audio.dataset.voiceAnswer = ''
    audio.src = objectUrl
    audio.onended = finish
    audio.onerror = deviceSpeech
    document.body.append(audio)
    updateStatus('playing')
    await audio.play()
  } catch {
    if (!stopped) deviceSpeech()
  }
  return controller
}

export type MicState = 'idle' | 'requesting' | 'recording' | 'transcribing' | 'recognizing'
export type QuestionRecorder = { stop: () => void; cancel: () => void }
type RecognitionEvent = { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }
type Recognition = {
  lang: string; continuous: boolean; interimResults: boolean
  onresult: ((event: RecognitionEvent) => void) | null
  onerror: (() => void) | null; onend: (() => void) | null
  start: () => void; stop: () => void; abort: () => void
}
type SpeechWindow = Window & {
  SpeechRecognition?: new () => Recognition
  webkitSpeechRecognition?: new () => Recognition
}
/** False when this browser can neither record audio nor recognise speech: the mic button is then not shown. */
export function voiceInputSupported(): boolean {
  if (typeof window === 'undefined') return false
  const browser = window as SpeechWindow
  return !!((globalThis.MediaRecorder && navigator.mediaDevices?.getUserMedia) || browser.SpeechRecognition || browser.webkitSpeechRecognition)
}
export const MIC_DENIED = 'Microphone access was denied. Allow it in your browser settings, or type your question.'
export const VOICE_UNAVAILABLE = 'Voice input is not available in this browser'

/** Recording is bounded to 30 seconds and 5 MB, matching the upload endpoint. */
export function recordQuestion(callbacks: {
  onText: (text: string) => void
  /** Words heard so far (device recognition only). */
  onInterim?: (text: string) => void
  onState: (state: MicState) => void
  onError: (message: string) => void
}): QuestionRecorder {
  let cancelled = false
  let stream: MediaStream | undefined
  let recorder: MediaRecorder | undefined
  let recognition: Recognition | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let bytes = 0
  const request = new AbortController()
  const chunks: Blob[] = []
  function release() {
    clearTimeout(timer)
    stream?.getTracks().forEach((track) => track.stop())
    stream = undefined
  }
  function fail(message: string) {
    release()
    if (recognition) {
      recognition.onresult = null; recognition.onerror = null; recognition.onend = null
      recognition.abort()
    }
    if (!cancelled) { callbacks.onError(message); callbacks.onState('idle') }
  }
  function browserRecognition() {
    if (cancelled) return
    const browser = window as SpeechWindow
    const Constructor = browser.SpeechRecognition ?? browser.webkitSpeechRecognition
    if (!Constructor) { fail(VOICE_UNAVAILABLE); return }
    try {
      recognition = new Constructor()
      recognition.lang = 'en-US'
      recognition.continuous = false
      recognition.interimResults = true
      recognition.onresult = (event) => {
        if (cancelled) return
        const words: string[] = []
        const heard: string[] = []
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) words.push(event.results[i][0].transcript)
          else heard.push(event.results[i][0].transcript)
        }
        const text = words.join(' ').trim()
        if (text) callbacks.onText(text)
        else if (heard.length) callbacks.onInterim?.(heard.join(' ').trim())
      }
      recognition.onerror = () => fail('Could not hear your question. Please try again or type it.')
      recognition.onend = () => { clearTimeout(timer); if (!cancelled) callbacks.onState('idle') }
      callbacks.onState('recognizing')
      recognition.start()
      timer = setTimeout(() => recognition?.stop(), 30_000)
    } catch { fail(VOICE_UNAVAILABLE) }
  }
  async function transcribe() {
    release()
    if (cancelled) return
    if (!bytes) { fail('No audio was recorded. Please try again.'); return }
    if (bytes > 5 * 1024 * 1024) { fail('The recording is too large. Please record a shorter question.'); return }
    callbacks.onState('transcribing')
    const mime = (recorder?.mimeType || chunks[0]?.type || 'audio/webm').split(';')[0]
    const form = new FormData()
    const extension = mime.includes('mp4') ? 'mp4' : mime.includes('ogg') ? 'ogg' : 'webm'
    form.append('file', new Blob(chunks, { type: mime }), `question.${extension}`)
    try {
      const response = await fetch('/api/speech-intent', {
        method: 'POST', body: form,
        signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]),
      })
      if (cancelled) return
      if (!response.ok) { browserRecognition(); return }
      const data: { fallback?: string; text?: string } = await response.json()
      if (cancelled) return
      if (data.fallback === 'device') { browserRecognition(); return }
      if (typeof data.text !== 'string' || !data.text.trim()) { fail('No speech was recognized. Please try again.'); return }
      callbacks.onText(data.text.trim())
      callbacks.onState('idle')
    } catch { if (!cancelled) browserRecognition() }
  }
  async function start() {
    callbacks.onState('requesting')
    if (!globalThis.MediaRecorder || !navigator.mediaDevices?.getUserMedia) { browserRecognition(); return }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (cancelled) { release(); return }
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus']
        .find((mime) => MediaRecorder.isTypeSupported(mime))
      recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorder.ondataavailable = (event) => {
        if (cancelled) return
        chunks.push(event.data)
        bytes += event.data.size
        if (bytes > 5 * 1024 * 1024 && recorder?.state === 'recording') recorder.stop()
      }
      recorder.onstop = () => { void transcribe() }
      recorder.onerror = () => { controller.cancel(); callbacks.onError('Could not record your question. Please try again.'); callbacks.onState('idle') }
      recorder.start(1000)
      callbacks.onState('recording')
      timer = setTimeout(() => controller.stop(), 30_000)
    } catch (err) {
      release()
      const name = err instanceof DOMException ? err.name : ''
      if (name === 'NotAllowedError' || name === 'SecurityError') { fail(MIC_DENIED); return }
      browserRecognition()
    }
  }
  const controller: QuestionRecorder = {
    stop() {
      clearTimeout(timer)
      if (recorder?.state === 'recording') recorder.stop()
      else if (recognition) recognition.stop()
      else { controller.cancel(); callbacks.onState('idle') }
    },
    cancel() {
      cancelled = true
      request.abort()
      if (recorder) {
        recorder.onstop = null
        recorder.ondataavailable = null
        recorder.onerror = null
        if (recorder.state === 'recording') recorder.stop()
      }
      if (recognition) {
        recognition.onresult = null; recognition.onerror = null; recognition.onend = null
        recognition.abort()
      }
      release()
    },
  }
  void start()
  return controller
}
