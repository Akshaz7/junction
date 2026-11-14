import { useEffect, useId, useMemo } from 'react';
import type { BuildState } from './rise';
import type { Viewer } from './viewer';
import { frameThrottle } from './frameThrottle';

/** Step slider under the 3D view: drag either way, play/pause, step back/forward. Never moves the camera. */
export function BuildSlider({ build, viewer }: { build: BuildState; viewer: Viewer | null }) {
  const id = useId();
  const scrub = useMemo(() => frameThrottle<number>((position) => viewer?.setBuildPosition(position)), [viewer]);
  useEffect(() => () => scrub.cancel(), [scrub]);
  const atEnd = build.phase === 'done';
  return <div className="viewer3d-build" data-testid="build-slider" role="group" aria-label="Build-up steps"
    data-phase={build.phase} data-step={build.index} data-total={build.total} data-playing={build.playing}>
    <button type="button" aria-label="Previous step" disabled={build.index <= 1}
      onClick={() => { scrub.cancel(); viewer?.setBuildStep(build.index - 1); }}>‹</button>
    <button type="button" aria-label={build.playing ? 'Pause build-up' : atEnd ? 'Replay build-up' : 'Play build-up'}
      aria-pressed={build.playing} onClick={() => { scrub.cancel(); if (build.playing) viewer?.pauseBuild(); else viewer?.playBuild(); }}>
      {build.playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}
    </button>
    <button type="button" aria-label="Next step" disabled={build.index >= build.total}
      onClick={() => { scrub.cancel(); viewer?.setBuildStep(build.index + 1); }}>›</button>
    <input id={id} type="range" aria-label="Build step" min={0} max={build.total} step={0.01} value={build.progress * build.total}
      aria-valuetext={`Step ${build.index} of ${build.total}, ${build.label}`}
      onChange={(event) => scrub.schedule(Number(event.target.value))} />
    <output htmlFor={id} aria-live="off" data-testid="build-step-label">Step {build.index} of {build.total} · {build.label}</output>
  </div>;
}
