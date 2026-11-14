import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLiveHighlightClient } from '../liveHighlight';
import { createChatLiveClient } from '../../lib/chat-live';

const ORIGIN = 'https://api.example-aiven.test';
class FakeSocket { static urls: string[] = []; readyState = 0; constructor(url: string) { FakeSocket.urls.push(url); }
  addEventListener() {} removeEventListener() {} send() {} close() {} }

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); FakeSocket.urls = []; });

describe('live sockets honour VITE_LIVE_ORIGIN', () => {
  it('no client opens a same-origin /ws when the live origin is set', () => {
    vi.stubEnv('VITE_LIVE_ORIGIN', ORIGIN);
    vi.stubGlobal('WebSocket', FakeSocket);
    const stop = [createLiveHighlightClient().onHighlight(() => {}), createChatLiveClient().subscribe(() => {})];
    expect(FakeSocket.urls.length).toBeGreaterThanOrEqual(2);
    for (const url of FakeSocket.urls) expect(url.startsWith('wss://api.example-aiven.test/ws')).toBe(true);
    stop.forEach((fn) => fn());
  });

  it('only live-url.ts builds a websocket origin; every other module uses liveSocketUrl', () => {
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) { if (name !== '__tests__') walk(path); continue; }
        if (!/\.tsx?$/.test(name) || /\.test\./.test(name) || name === 'live-url.ts') continue;
        const text = readFileSync(path, 'utf8');
        if (/location\.host|`\$\{[^}]*\}\/ws|['"`]\/ws[?'"`]/.test(text)) offenders.push(path);
      }
    };
    walk(join(process.cwd(), 'src'));
    expect(offenders).toEqual([]);
  });
});
