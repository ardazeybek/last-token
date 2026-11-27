// Checks cold-cache pruning: stubs picked only after a cold gap, kept stable afterwards, recent turns whole.
import { test, expect } from 'claude-code/testing'
import { pruneBody, cacheLines, pruneQuota, applyCut, lastPrompt, hash } from './register'

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

// Cold digest: history before the newest prompt becomes one digest block; a changed prompt drops the cut.
test('applyCut keeps the prompt behind the digest and refuses a changed history', () => {
  const m = conv().messages.slice(0, 5)
  const n = lastPrompt(m)
  expect(n).toBe(4)
  const cut = { n, head: hash(JSON.stringify(m[n].content)), digest: '[last-token compaction: d' }
  const out: any = applyCut(m, cut)
  expect(out.length).toBe(1)
  expect(out[0].content[0].text).toBe('[last-token compaction: d')
  expect(out[0].content[1].text).toBe('yeni istek')
  const later = [...m, { role: 'assistant', content: [{ type: 'text', text: 'ok' }] }, { role: 'user', content: 'sonra' }]
  expect((applyCut(later, cut) as any).length).toBe(3)
  expect(applyCut(m.slice(0, 3), cut)).toBe(null)
})

test('lastPrompt is -1 while a tool result is pending', () => {
  expect(lastPrompt(conv().messages.slice(0, 3))).toBe(-1)
})
