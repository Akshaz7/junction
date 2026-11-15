/**
 * Hover tooltip for plan-map items in the 2D viewer: a small pill next to the cursor with a
 * one-line summary (see lib/plan-item-summary). Purely visual: pointer-events none, positioned
 * 14px from the pointer and flipped left/up so it stays inside the stage container.
 */
import { useLayoutEffect, useRef, useState, type JSX } from 'react'
import { kindStyle } from '../../lib/kind-colors'
import './plan-hover-tip.css'

export const TIP_OFFSET = 14
const EDGE = 4
const TIP_H = 26

/** Rough pill width before the browser has measured it (and in jsdom, which never measures). */
export function estimateTipWidth(text: string): number { return Math.round(text.length * 6.6 + 30) }

/** Top-left corner for a tip of size w × h at pointer (x, y), flipped and clamped inside the container. */
export function tipSpot(x: number, y: number, w: number, h: number, cw: number, ch: number): { left: number; top: number; flipX: boolean; flipY: boolean } {
  const flipX = x + TIP_OFFSET + w > cw - EDGE
  const flipY = y + TIP_OFFSET + h > ch - EDGE
  let left = flipX ? x - TIP_OFFSET - w : x + TIP_OFFSET
  let top = flipY ? y - TIP_OFFSET - h : y + TIP_OFFSET
  left = Math.max(EDGE, Math.min(left, cw - EDGE - w))
  top = Math.max(EDGE, Math.min(top, ch - EDGE - h))
  return { left: Math.round(left), top: Math.round(top), flipX, flipY }
}

/** Kind word at the start of a summary ("Wall · …", "Room 2.01 …") for the colour dot. */
function leadKind(text: string): string {
  const w = text.split(/[\s·]/)[0]?.toLowerCase() ?? ''
  return w === 'double' ? 'door' : w
}

export function PlanHoverTip(props: { text: string | null; x: number; y: number; containerWidth: number; containerHeight: number }): JSX.Element | null {
  const { text, x, y, containerWidth, containerHeight } = props
  const ref = useRef<HTMLDivElement>(null)
  const [measured, setMeasured] = useState<{ text: string; w: number; h: number } | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !text) return
    const w = el.offsetWidth, h = el.offsetHeight
    if (w > 0 && h > 0 && (measured?.text !== text || measured.w !== w || measured.h !== h)) setMeasured({ text, w, h })
  }, [text, measured])

  if (!text || !Number.isFinite(x) || !Number.isFinite(y)) return null
  const maxW = Math.max(40, Math.min(320, containerWidth - 2 * EDGE))
  const size = measured?.text === text ? measured : { w: Math.min(estimateTipWidth(text), maxW), h: TIP_H }
  const spot = tipSpot(x, y, size.w, size.h, containerWidth, containerHeight)
  const color = kindStyle(leadKind(text)).color

  return (
    <div
      ref={ref}
      className="plan-hover-tip"
      role="tooltip"
      data-testid="plan-hover-tip"
      data-flip-x={spot.flipX ? 'true' : undefined}
      data-flip-y={spot.flipY ? 'true' : undefined}
      style={{ left: spot.left, top: spot.top, maxWidth: maxW }}
    >
      <span className="plan-hover-tip-dot" style={{ background: color }} aria-hidden="true" />
      <span className="plan-hover-tip-text">{text}</span>
    </div>
  )
}
