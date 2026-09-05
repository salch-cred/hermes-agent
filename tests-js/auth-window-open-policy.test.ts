/**
 * Security regression for the GHSA-9f4c-93c8-jc8g class, auth-window arm:
 * the OAuth login, portal sign-in, and silent portal-renewal windows load
 * REMOTE content (the OAuth redirect chain passes through third-party IDP
 * pages; the portal page is fetched over the network), so any window.open
 * reaching their webContents is content-driven and must be denied — never
 * opened as a side effect. These import the real policy module main.ts
 * wires the auth windows with.
 */

import assert from 'node:assert/strict'

import { describe, test } from 'vitest'

import { wireAuthWindowOpenPolicy } from '../apps/desktop/electron/window-open-policy'

function makeFakeAuthWindow() {
  const calls = { windowOpenHandlers: [] as Array<(details: { url: string }) => { action: string }>, logs: [] as string[] }

  const win = {
    webContents: {
      setWindowOpenHandler(handler: (details: { url: string }) => { action: string }) {
        calls.windowOpenHandlers.push(handler)
      }
    }
  }

  return { win, calls }
}

describe('auth window-open policy (GHSA-9f4c-93c8-jc8g class)', () => {
  test('every auth flow installs exactly one always-deny handler', () => {
    for (const label of ['oauth', 'portal', 'portal-renew']) {
      const { win, calls } = makeFakeAuthWindow()
      const logs: string[] = []

      wireAuthWindowOpenPolicy(win, label, (line: string) => logs.push(line))

      assert.equal(calls.windowOpenHandlers.length, 1)

      const handler = calls.windowOpenHandlers[0]
      assert.deepEqual(handler({ url: 'https://idp.attacker.test/login?next=steal' }), { action: 'deny' })
      assert.deepEqual(handler({ url: 'file:///etc/passwd' }), { action: 'deny' })
      assert.deepEqual(handler({ url: 'javascript:alert(1)' }), { action: 'deny' })

      // The deny log names the flow and carries origin only — a signed URL
      // or query token must never reach the persisted desktop log.
      assert.ok(logs.length >= 1)
      assert.ok(logs.every(line => line.startsWith(`[window-open] ${label} denied: `)))
      assert.ok(logs.every(line => !line.includes('next=steal')))
    }
  })

  test('a missing or throwing logger never degrades the deny', () => {
    const silent = makeFakeAuthWindow()
    wireAuthWindowOpenPolicy(silent.win, 'oauth')
    assert.deepEqual(silent.calls.windowOpenHandlers[0]({ url: 'https://x.test/' }), { action: 'deny' })

    const throwing = makeFakeAuthWindow()
    wireAuthWindowOpenPolicy(throwing.win, 'portal', () => {
      throw new Error('logging blew up')
    })
    assert.deepEqual(throwing.calls.windowOpenHandlers[0]({ url: 'https://x.test/' }), { action: 'deny' })
  })
})
