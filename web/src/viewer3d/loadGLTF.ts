import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { restoreStaticGLTF, type StaticGLTFData } from './gltfTransfer';

export interface LoadProgress {
  phase: 'manifest' | 'download' | 'parse' | 'prepare';
  loaded?: number;
  total?: number;
}
export interface SceneLoadOptions {
  signal?: AbortSignal;
  onProgress?: (progress: LoadProgress) => void;
}
const WORKER_MIN_BYTES = 5 * 1024 * 1024;

/** Some image/decoder promises inside GLTFLoader cannot be aborted. Bound the UI
 * wait too; loadScene disposes any geometry that eventually arrives after abort. */
export function withAbort<T>(task: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const abort = () => reject(signal.reason ?? new DOMException('Scene load cancelled', 'AbortError'));
    const finish = (callback: () => void) => { signal.removeEventListener('abort', abort); callback(); };
    signal.addEventListener('abort', abort, { once: true });
    task.then((value) => finish(() => resolve(value)), (error) => finish(() => reject(error)));
    if (signal.aborted) abort();
  });
}

async function readGeometry(url: string, { signal, onProgress }: SceneLoadOptions): Promise<ArrayBuffer> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Could not load 3D geometry (${response.status})`);
  const length = Number(response.headers.get('content-length'));
  const total = length > 0 ? length : undefined;
  onProgress?.({ phase: 'download', loaded: 0, total });
  if (!response.body) return response.arrayBuffer();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0, lastProgress = 0;
  try {
    while (true) {
      signal?.throwIfAborted();
      const next = await reader.read();
      if (next.done) break;
      chunks.push(next.value);
      loaded += next.value.byteLength;
      if (performance.now() - lastProgress > 100) {
        onProgress?.({ phase: 'download', loaded, total });
        lastProgress = performance.now();
      }
    }
  } finally { reader.releaseLock(); }
  signal?.throwIfAborted();
  const buffer = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.byteLength; }
  onProgress?.({ phase: 'download', loaded, total });
  return buffer.buffer;
}

export async function loadGLTF(url: string, options: SceneLoadOptions): Promise<Pick<GLTF, 'scene' | 'parser'>> {
  const { signal, onProgress } = options;
  signal?.throwIfAborted();
  const buffer = await readGeometry(url, options);
  const resourcePath = new URL('.', url).href;
  onProgress?.({ phase: 'parse' });
  if (buffer.byteLength < WORKER_MIN_BYTES || typeof Worker === 'undefined') {
    const gltf = await new GLTFLoader().parseAsync(buffer, resourcePath);
    return gltf;
  }
  // Vite bundles the same MIT three.js loader into a dedicated module worker.
  const worker = new Worker(new URL('./gltf.worker.ts', import.meta.url), { type: 'module' });
  try {
    const result = await new Promise<{ data?: StaticGLTFData; fallback?: ArrayBuffer }>((resolve, reject) => {
      const abort = () => reject(signal?.reason ?? new DOMException('Scene load cancelled', 'AbortError'));
      const finish = (callback: () => void) => { signal?.removeEventListener('abort', abort); callback(); };
      worker.onmessage = (event: MessageEvent<{ data?: StaticGLTFData; fallback?: ArrayBuffer; error?: string }>) => {
        finish(() => event.data.error ? reject(new Error(event.data.error)) : resolve(event.data));
      };
      worker.onerror = (event) => finish(() => reject(new Error(event.message || 'Could not parse the 3D model')));
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) { abort(); return; }
      worker.postMessage({ buffer, resourcePath }, [buffer]);
    });
    worker.terminate();
    signal?.throwIfAborted();
    onProgress?.({ phase: 'prepare' });
    if (result.data) return await restoreStaticGLTF(result.data, signal);
    if (result.fallback) return await new GLTFLoader().parseAsync(result.fallback, resourcePath);
    throw new Error('No geometry returned by the 3D parser');
  } finally { worker.terminate(); }
}
