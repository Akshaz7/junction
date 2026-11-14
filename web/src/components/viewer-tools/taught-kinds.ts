/** Standard item kinds a user can mark something as. Ids match the engine's plan-map kinds. */
export const TAUGHT_KINDS = [
  { id: 'door', label: 'Door' }, { id: 'window', label: 'Window' }, { id: 'wall', label: 'Wall' }, { id: 'toilet', label: 'Toilet' },
  { id: 'sink', label: 'Sink' }, { id: 'shower', label: 'Shower' }, { id: 'bathtub', label: 'Bathtub' }, { id: 'stairs', label: 'Stairs' },
  { id: 'column', label: 'Column' }, { id: 'duct', label: 'Duct' }, { id: 'terminal', label: 'Air terminal' }, { id: 'pipe', label: 'Pipe' },
  { id: 'valve', label: 'Valve' }, { id: 'fixture', label: 'Fixture' },
] as const

const WORDS: Record<string, string> = {
  door: 'door', doors: 'door', dr: 'door', ovi: 'door', window: 'window', windows: 'window', ikkuna: 'window', wall: 'wall', walls: 'wall',
  toilet: 'toilet', wc: 'toilet', sink: 'sink', washbasin: 'sink', 'wash basin': 'sink', shower: 'shower', bathtub: 'bathtub', 'bath tub': 'bathtub',
  stair: 'stairs', stairs: 'stairs', staircase: 'stairs', column: 'column', columns: 'column', pillar: 'column', duct: 'duct', ducts: 'duct',
  terminal: 'terminal', terminals: 'terminal', diffuser: 'terminal', 'air terminal': 'terminal', 'supply air terminal': 'terminal', 'extract air terminal': 'terminal',
  pipe: 'pipe', pipes: 'pipe', valve: 'valve', valves: 'valve', 'fire damper': 'valve', fixture: 'fixture', fixtures: 'fixture',
}

/** The standard kind a typed name counts as, or null for the user's own kind. Mirrors the server's synonym table for the common words. */
export function kindFor(text: string): { id: string; label: string } | null {
  const id = WORDS[text.trim().toLowerCase().replace(/\s+/g, ' ')]
  return TAUGHT_KINDS.find((kind) => kind.id === id) ?? null
}
export const kindLabel = (id: string | null | undefined, fallback = '') => TAUGHT_KINDS.find((kind) => kind.id === id)?.label ?? fallback
