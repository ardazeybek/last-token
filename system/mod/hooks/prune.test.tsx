// Checks cold-cache pruning: stubs picked only after a cold gap, kept stable afterwards, recent turns whole.
import { test, expect } from 'claude-code/testing'
import { pruneBody, cacheLines, pruneQuota } from './register'

const C = { coldSeconds: 3630, pruneKeepTurns: 1, pruneMinChars: 100 }
const big = 'x'.repeat(2000)
const conv = () => ({ model: 'm', messages: [
  { role: 'user', content: 'ilk istek' },
  { role: 'assistant', content: [{ type: 'tool_use', id: 't1', name: 'Read', input: {} }] },
  { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't1', content: big, cache_control: { type: 'ephemeral' } }] },
  { role: 'assistant', content: [{ type: 'text', text: 'okudum' }] },
  { role: 'user', content: [{ type: 'text', text: 'yeni istek' }] },
  { role: 'assistant', content: [{ type: 'tool_use', id: 't2', name: 'Read', input: {} }] },
  { role: 'user', content: [{ type: 'tool_result', tool_use_id: 't2', content: big }] },
] })

test('warm cache: nothing changes', () => {
  const r = pruneBody(conv(), { t: 1000, ids: [] }, 1000 + 60_000, C)!
  expect(r.body).toBe(null)
  expect(r.st.t).toBe(61_000)
})

test('cold cache: old big outputs become stubs, the newest turn stays whole, cache_control kept', () => {
  const r = pruneBody(conv(), { t: 1000, ids: [] }, 1000 + 3700_000, C)!
  expect(r.added).toBe(1)
  expect(r.st.ids).toEqual(['t1'])
  const m = r.body.messages
  expect(m[2].content[0].content).toContain('last-token')
  expect(m[2].content[0].cache_control).toEqual({ type: 'ephemeral' })
  expect(m[6].content[0].content).toBe(big)
})

test('later warm requests apply the same stubs (stable prefix)', () => {
  const r = pruneBody(conv(), { t: 5000, ids: ['t1'] }, 6000, C)!
  expect(r.added).toBe(0)
  expect(r.body.messages[2].content[0].content).toContain('last-token')
})

test('a new conversation is never pruned on its first request', () => {
  const r = pruneBody(conv(), { t: 0, ids: [] }, 9e12, C)!
  expect(r.body).toBe(null)
})

test('pane rows: cache re-writes by cause, and the prune quota by model', () => {
  const s: any = { cache: { busts: { idle: { n: 2, tokens: 200000 }, prefix: { n: 0, tokens: 0 } }, idle_compactions: 0, bust_quota: 0.92 } }
  expect(cacheLines(s)[0].text).toContain('2 long pause(s)')
  expect(cacheLines({ cache: { busts: {}, idle_compactions: 0 } } as any)[0].text).toContain('No cache busts')
  expect(Math.round(pruneQuota(100000, 'claude-opus-5-5') * 100)).toBe(230)
  expect(Math.round(pruneQuota(100000, 'claude-haiku-5-5') * 100)).toBe(46)
})
