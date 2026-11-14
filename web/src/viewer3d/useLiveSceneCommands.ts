import { useEffect } from 'react';
import { bindLiveCommands } from './liveViewerHighlight';
import type { Viewer } from './viewer';

/** For hosts using createViewer directly. Viewer3D already binds while geometry loads. */
export function useLiveSceneCommands(viewer: Viewer | null, docId?: string): void {
  useEffect(() => {
    if (!viewer) return;
    const live = bindLiveCommands(viewer, docId);
    live.sceneReady();
    return () => live.dispose();
  }, [viewer, docId]);
}
