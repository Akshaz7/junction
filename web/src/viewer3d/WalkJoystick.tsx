import { useRef, useState, type PointerEvent } from 'react';

/** The left thumb moves; a second touch can drag the canvas to look. */
export function WalkJoystick({ onMove }: { onMove(x: number, y: number): void }) {
  const pointer = useRef<number | null>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  function move(event: PointerEvent<HTMLDivElement>) {
    if (pointer.current !== event.pointerId) return;
    const box = event.currentTarget.getBoundingClientRect();
    let x = (event.clientX - box.left - box.width / 2) / 36;
    let y = (event.clientY - box.top - box.height / 2) / 36;
    const length = Math.hypot(x, y);
    if (length > 1) { x /= length; y /= length; }
    onMove(x, y); setOffset({ x, y });
  }
  function stop(event: PointerEvent<HTMLDivElement>) {
    if (pointer.current !== event.pointerId) return;
    pointer.current = null; onMove(0, 0); setOffset({ x: 0, y: 0 });
  }
  return <div className="viewer3d-walk-touch">
    <div className="viewer3d-walk-joystick" role="group" aria-label="Walk movement joystick"
      onPointerDown={(event) => {
        event.preventDefault();
        if (pointer.current !== null) return;
        pointer.current = event.pointerId;
        event.currentTarget.setPointerCapture(event.pointerId);
        move(event);
      }} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop}>
      <span style={{ transform: `translate(${offset.x * 36}px, ${offset.y * 36}px)` }} />
    </div>
    <span className="viewer3d-walk-look-help">Drag here to look</span>
  </div>;
}
