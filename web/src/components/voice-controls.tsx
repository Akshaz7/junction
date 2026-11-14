import { useEffect, useId, useRef, useState } from 'react'
import { LoaderCircle, Mic, Square, Volume2 } from 'lucide-react'
import { recordQuestion, speakAnswer, type MicState, type QuestionRecorder, type SpeechController, type SpeechStatus } from '../lib/voice'
import './voice-controls.css'

export function SpeakButton({ text, disabled = false }: { text: string; disabled?: boolean }) {
  const [active, setActive] = useState(false)
  const [status, setStatus] = useState<SpeechStatus | 'loading' | null>(null)
  const control = useRef<SpeechController | null>(null)
  const request = useRef<AbortController | null>(null)
  const hintId = useId()
  useEffect(() => () => {
    request.current?.abort(); control.current?.stop()
    request.current = null; control.current = null
  }, [text, disabled])
  useEffect(() => { setActive(false); setStatus(null) }, [text, disabled])
  async function toggle() {
    if (request.current) {
      request.current.abort(); control.current?.stop()
      request.current = null; control.current = null
      setActive(false); setStatus(null)
      return
    }
    const pending = new AbortController()
    request.current = pending
    setActive(true); setStatus('loading')
    const speech = await speakAnswer(text, {
      signal: pending.signal, onStatus: (next) => { if (!pending.signal.aborted) setStatus(next) },
    })
    if (pending.signal.aborted) { speech.stop(); return }
    control.current = speech
    setStatus(speech.status)
    await speech.finished
    if (pending.signal.aborted) return
    setActive(false)
    setStatus(speech.status === 'error' ? 'error' : null)
    request.current = null; control.current = null
  }
  return <span className="voice-control">
    <button type="button" className="voice-button" aria-label={active ? 'Stop' : 'Play spoken answer'} aria-pressed={active}
      aria-describedby={status === 'fallback' || status === 'error' ? hintId : undefined}
      disabled={disabled || !text.trim()} onClick={() => { void toggle() }}>
      {active ? <Square size={14} aria-hidden="true" /> : <Volume2 size={16} aria-hidden="true" />}
    </button>
    <span id={hintId} className="voice-hint" role="status">{status === 'fallback' ? 'device voice' : status === 'error' ? 'Spoken audio is not available' : ''}</span>
  </span>
}

export function MicButton({ onText, disabled = false }: { onText: (text: string) => void; disabled?: boolean }) {
  const [state, setState] = useState<MicState>('idle')
  const [error, setError] = useState('')
  const control = useRef<QuestionRecorder | null>(null)
  const onTextRef = useRef(onText)
  const hintId = useId()
  onTextRef.current = onText
  useEffect(() => () => { control.current?.cancel(); control.current = null }, [disabled])
  useEffect(() => { setState('idle'); setError('') }, [disabled])
  const active = state !== 'idle'
  const hint = error || (state === 'requesting' ? 'Allow microphone access' : state === 'recording' || state === 'recognizing' ? 'Listening… Click to stop' : state === 'transcribing' ? 'Transcribing…' : '')
  function toggle() {
    if (active) { control.current?.stop(); return }
    control.current?.cancel()
    setError('')
    control.current = recordQuestion({
      onText: (text) => onTextRef.current(text), onState: setState, onError: setError,
    })
  }
  return <span className="voice-control">
    <button type="button" className="voice-button" aria-label="Speak a question" aria-pressed={active}
      aria-describedby={hint ? hintId : undefined} disabled={disabled} onClick={toggle}>
      {state === 'transcribing' ? <LoaderCircle size={16} aria-hidden="true" /> : active ? <Square size={14} aria-hidden="true" /> : <Mic size={16} aria-hidden="true" />}
    </button>
    <span id={hintId} className="voice-hint" role="status">{hint}</span>
  </span>
}
