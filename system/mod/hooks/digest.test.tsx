// Checks the digest row (never drawn as the person's message, on any surface) and the savings pane.
import { test, expect } from 'claude-code/testing'

import { fmtQuota, fmtTokens } from './register'

const DIGEST = '[last-token compaction: older turns were replaced. Full log: .ctx/archive/L039-log.md]\nLatest user request'
const row = (surface: 'terminal' | 'desktop' | 'vscode' | 'mobile', text: string, isExpanded: boolean) =>
  ({ plugin: 'last-token', surface, component: 'UserMessage', props: { text, origin: { kind: 'composer' }, isExpanded } }) as const

for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
  test(`digest row is one line on ${surface}`, async ($) => {
    const out = await $.ui.mount(row(surface, DIGEST, false))
    expect((await out.find({ type: 'Text', text: /compacted/ }))?.text).toContain('L039')
    expect(await out.find({ type: 'Text', text: /Latest user request/ })).toBeFalsy()
  })
  test(`normal prompt untouched on ${surface}`, async ($) => {
    const out = await $.ui.mount(row(surface, 'merhaba', false))
    expect(await out.find({ type: 'Text', text: /compacted/ })).toBeFalsy()
  })
}

// Surfaces without ctrl+o pass isExpanded: true; the digest must still be one line there.
for (const surface of ['desktop', 'vscode', 'mobile'] as const) {
  test(`digest stays folded on ${surface} even when expanded, button shows it`, async ($) => {
    const out = await $.ui.mount(row(surface, DIGEST, true))
    expect(await out.find({ type: 'Text', text: /Latest user request/ })).toBeFalsy()
    await out.press({ key: 'digest-L039' })
    expect(await out.find({ type: 'Text', text: /Latest user request/ })).toBeTruthy()
    await out.press({ key: 'digest-L039' })
    expect(await out.find({ type: 'Text', text: /Latest user request/ })).toBeFalsy()
  })
}

test('terminal ctrl+o shows the whole digest', async ($) => {
  const out = await $.ui.mount(row('terminal', DIGEST, true))
  expect(await out.find({ type: 'Text', text: /compacted/ })).toBeFalsy()
})

const PANE = {
  plugin: 'last-token', component: 'Pane', requestId: 'last-token-savings',
  props: { title: 'Quota savings', isFocused: false, bodyColumns: 40, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

test('pane says when nothing is measured yet', async ($) => {
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text' }))?.text).toContain('Last Token is running')
  await ui.unmount()
})

test('pane shows the measured savings on every surface', async ($, on) => {
  const S = { requests: 180, sent: 13165360, saved: 4215145, compactions: 1, deterministic: 1, context: 93594, pct: 24,
    quota: 3.82, quota_sub: 0.5, quota_saved: 1.17, quota_pct: 23, model: 'claude-haiku-5-5', measured: true,
    mode: 'global' as const, label: '/home/u', store: '/s/.ctx', checks: [{ name: 'Early compaction', ok: true, detail: '130K' }] }
  on('state.get', (_, e, next) => (e.key === 'savings' ? { value: { value: S, version: 1 } } : next(e)))
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /less\)/ }))?.text).toBe('Quota saved: −1.17 pts  (23% less)')
    expect((await ui.find({ type: 'Text', text: /session used/ }))?.text).toBe('This session used: ~3.82 pts (subagents 0.50)')
    expect((await ui.find({ type: 'Text', text: /not re-read/ }))?.text).toBe('Context not re-read: −4.2M tokens · current context 94K')
    expect((await ui.find({ type: 'Text', text: /active in/ }))?.text).toBe('✓ Last Token is active in this session')
    expect((await ui.find({ type: 'Text', text: /Global mode/ }))?.text).toBe('Global mode: /home/u')
    await ui.unmount()
  }
})

test('pane warns when a part is missing', async ($, on) => {
  const S = { requests: 1, sent: 10, saved: 0, compactions: 0, deterministic: 0, context: 10, pct: 0, mode: 'project' as const,
    label: 'BayGun', store: '/p/.ctx', checks: [{ name: 'Archive (PreCompact)', ok: false, detail: '' }] }
  on('state.get', (_, e, next) => (e.key === 'savings' ? { value: { value: S, version: 1 } } : next(e)))
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /partly/ }))?.text).toBe('⚠ Last Token is partly working')
  expect((await ui.find({ type: 'Text', text: /✗/ }))?.text).toBe('✗ Archive (PreCompact)')
  expect((await ui.find({ type: 'Text', text: /Project/ }))?.text).toBe('Project: BayGun')
  await ui.unmount()
})

test('number helpers', () => {
  expect(fmtTokens(4215145)).toBe('4.2M')
  expect(fmtTokens(93594)).toBe('94K')
  expect(fmtTokens(12)).toBe('12')
  expect(fmtQuota(0.4211)).toBe('0.42')
  expect(fmtQuota(-1)).toBe('0.00')
  expect(fmtQuota(23.6)).toBe('24')
})
