import { storeyName, type SceneManifest, type Storey } from './scene';

/** CONTRACT 5.5; quantities and properties are optional facts, never inferred. */
export interface IFCElement {
  item_id: string;
  name?: string | null;
  kind?: string | null;
  ifc_class?: string | null;
  predefined_type?: string | null;
  type_name?: string | null;
  storey?: Storey | null;
  quantities?: Record<string, number | null> | null;
  props?: Record<string, unknown> | null;
}

export interface ItemDetails {
  item_id: string;
  name: string;
  fields: { label: string; value: string }[];
  hasElement: boolean;
}

/** Supports the pipeline's {elements: [...]} envelope and a plain entry array. */
export function indexElements(data: unknown): Map<string, IFCElement> {
  const entries = Array.isArray(data) ? data
    : data && typeof data === 'object' && 'elements' in data ? data.elements : null;
  if (!Array.isArray(entries)) throw new Error('Invalid IFC element index');
  return new Map(entries.filter((entry): entry is IFCElement =>
    entry !== null && typeof entry === 'object' && typeof entry.item_id === 'string',
  ).map((entry) => [entry.item_id, entry]));
}

function text(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return null;
}

export function buildItemDetails(
  manifest: SceneManifest, item_id: string, element?: IFCElement,
): ItemDetails | null {
  const sceneItem = manifest.items[item_id];
  if (!sceneItem) return null;
  // Never combine metadata from a different item with this scene selection.
  if (element?.item_id !== item_id) element = undefined;
  const fields: ItemDetails['fields'] = [
    { label: 'Kind', value: text(element?.kind) ?? sceneItem.kind },
    { label: 'Storey', value: storeyName(element?.storey ?? sceneItem.storey) ?? 'Not available' },
  ];
  function add(label: string, value: unknown) {
    const formatted = text(value);
    if (formatted !== null) fields.push({ label, value: formatted });
  }
  add('IFC class', element?.ifc_class);
  add('Type', element?.type_name);
  add('Predefined type', element?.predefined_type);
  for (const [key, label, unit] of [
    ['width_m', 'Width', 'm'], ['height_m', 'Height', 'm'], ['length_m', 'Length', 'm'],
    ['area_m2', 'Area', 'm²'], ['volume_m3', 'Volume', 'm³'],
  ]) {
    const value = element?.quantities?.[key];
    if (typeof value === 'number' && Number.isFinite(value)) add(label, `${value} ${unit}`);
  }
  add('Material', element?.props?.material);
  add('Fire rating', element?.props?.fire_rating);
  add('External', element?.props?.is_external);
  return { item_id, name: text(element?.name) ?? item_id, fields, hasElement: element !== undefined };
}
