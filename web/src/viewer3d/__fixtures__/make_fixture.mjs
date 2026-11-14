import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const target = new URL('./digital_hub/', import.meta.url);
const source = new URL('../../../../out/digital_hub_arc.elements.json', import.meta.url);
const model = new URL('../../../../out/digital_hub_arc.glb', import.meta.url);
const elementsFile = JSON.parse(await readFile(source, 'utf8'));
const elements = Array.isArray(elementsFile) ? elementsFile : elementsFile.elements;
const kinds = new Set(['wall', 'door', 'window', 'room', 'toilet', 'sink', 'shower', 'bathtub', 'stairs', 'column', 'text', 'dimension', 'other']);

// The spike's boxes are IFC Z-up. Its copied GLB uses (x, z, -y).
// No extra translation is applied: this local fixture retains the spike origin.
function bounds(element) {
  if (element.bbox_m) return element.bbox_m;
  const min = element.bbox_min;
  const max = element.bbox_max;
  return min && max ? [[min[0], min[2], -max[1]], [max[0], max[2], -min[1]]] : null;
}

await mkdir(target, { recursive: true });
const bundled = (await stat(model)).size < 10 * 1024 * 1024;
if (bundled) await copyFile(model, new URL('scene.glb', target));
const manifest = {
  doc_id: 'ifc-bench__digital-hub-arc',
  glb: bundled ? 'scene.glb' : '../../../../../out/digital_hub_arc.glb',
  usdz: null,
  units: 'm',
  up: 'Y',
  origin_offset_m: [0, 0, 0],
  storeys: elementsFile.storeys ?? [],
  items: Object.fromEntries(elements.map((element) => {
    const id = element.item_id ?? element.guid;
    if (typeof id !== 'string') throw new Error('Element has no item_id or IFC GlobalId');
    let kind = element.kind ?? element.category;
    if (kind === 'space') kind = 'room';
    if (kind === 'stair') kind = 'stairs';
    return [id, {
      node: id,
      usd_name: `i_${createHash('sha1').update(id).digest('hex').slice(0, 16)}`,
      bbox_m: bounds(element),
      storey: element.storey ?? null,
      kind: kinds.has(kind) ? kind : 'other',
    }];
  })),
};
await writeFile(new URL('scene.json', target), `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Wrote ${fileURLToPath(new URL('scene.json', target))}; GLB ${bundled ? 'bundled' : 'referenced from out/'}`);
