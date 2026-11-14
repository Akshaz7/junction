import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { transferStaticGLTF } from './gltfTransfer';

// Avoid DOM/image-dependent features in this worker. Unsupported assets return
// their original buffer for the full loader; no second network request is made.
self.onmessage = async (event: MessageEvent<{ buffer: ArrayBuffer; resourcePath: string }>) => {
  const { buffer, resourcePath } = event.data;
  try {
    const view = new DataView(buffer);
    if (view.getUint32(0, true) !== 0x46546c67) throw new Error('Not a binary glTF');
    const jsonLength = view.getUint32(12, true);
    const json = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 20, jsonLength)));
    if (json.images?.length || json.skins?.length || json.animations?.length || json.cameras?.length
      || json.extensionsUsed?.includes('EXT_mesh_gpu_instancing')
      || json.buffers?.some((entry: { uri?: string }) => entry.uri)) {
      self.postMessage({ fallback: buffer }, { transfer: [buffer] });
      return;
    }
    const gltf = await new GLTFLoader().parseAsync(buffer, resourcePath);
    try {
      const { data, buffers } = transferStaticGLTF(gltf);
      self.postMessage({ data }, { transfer: buffers });
    } catch {
      self.postMessage({ fallback: buffer }, { transfer: [buffer] });
    }
  } catch (reason) {
    self.postMessage({ error: reason instanceof Error ? reason.message : String(reason) });
  }
};
