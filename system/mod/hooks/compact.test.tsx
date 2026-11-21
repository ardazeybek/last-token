// Checks compaction modes, the desktop placeholder folder and the pane opening without a surface.
import { test, expect } from 'claude-code/testing'

const EXTRA = '[last-token compaction: kept verbatim next to the summary above. Archive of everything: .ctx/archive/L001-log.md]\n- the real request'
const SUMMARY = { role: 'user' as const, text: 'Model summary of the conversation', toolUses: [] }

// Stand in for a last-token project at `root` whose ctx.py answers `stdout`; records each ctx.py call.
function project(on: any, root: string, stdout: string, modJson?: string, noPython3 = false) {
  const calls: string[][] = []
  on('session.root', () => ({ value: root }))
  on('session.id', () => ({ value: 'sid-1' }))
  on('fs.exists', (_: any, e: any) => ({ value: e.path === `${root}/.ctx/ctx.py` }))
  on('fs.read', (_: any, e: any) => (modJson && e.path === `${root}/.ctx/mod.json` ? { value: modJson } : { deny: 'no file' }))
  on('process.run', (_: any, e: any) => {
    calls.push([...e.argv])
    if (noPython3 && e.argv[0] === 'python3') throw new Error("failed to start: ENOENT: posix_spawn 'python3'")
    return { value: { exitCode: 0, stdout, stderr: '' } }
  })
  on('session.compact', () => ({ messages: [SUMMARY] }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('command.register', () => ({ value: undefined }))
  return calls
}

test('summary mode keeps the model summary and adds the verbatim block', async ($, on) => {
  const calls = project(on, '/p', EXTRA, '{"compact": "summary"}')
  const r: any = await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: 'old conversation', toolUses: [] }] } as any)
  expect(r.messages.length).toBe(2)
  expect(r.messages[0].text).toBe(SUMMARY.text)
  expect(r.messages[1].text).toContain('the real request')
  expect(calls.some(a => a.includes('compact-summary') && a.includes('--extra'))).toBe(true)
})

test('digest (default) replaces the history with the digest only', async ($, on) => {
  project(on, '/p', '[last-token compaction: older turns were replaced. Full log: .ctx/archive/L002-log.md]')
  const r: any = await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: 'old conversation', toolUses: [] }] } as any)
  expect(r.messages.length).toBe(1)
  expect(r.messages[0].text).toContain('L002')
})

test('digest mode falls back to the engine when ctx.py prints nothing (paused session)', async ($, on) => {
  project(on, '/p', '', '{"compact": "digest"}')
  const r: any = await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: 'old conversation', toolUses: [] }] } as any)
  expect(r.messages[0].text).toBe(SUMMARY.text)
})

test('desktop placeholder folder: last-token stays out of the way', async ($, on) => {
  const calls = project(on, '/home/u/.claude/spares/spare-AbC', EXTRA)
  const r: any = await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: 'old conversation', toolUses: [] }] } as any)
  expect(r.messages.length).toBe(1)
  expect(calls.length).toBe(0)
})

const PANEL_JSON = JSON.stringify({ requests: 1, sent: 10, saved: 0, compactions: 0, deterministic: 0, context: 10, pct: 0,
  mode: 'project', label: 'p', store: '/p/.ctx', checks: [] })

test('developer view (panel: true): the pane opens even when no surface is listed (desktop)', async ($, on) => {
  const opened: string[] = []
  project(on, '/p', PANEL_JSON, '{"panel": true}')
  on('session.surfaces', () => ({ value: [] }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.open', (_: any, e: any) => { opened.push(e.id); return { value: { isPlaced: false, reason: 'no surface yet' } } })
  await $.session.start({ cwd: '/p', surface: null, isInteractive: true })
  expect(opened).toEqual(['last-token-savings'])
})

test('default: no pane, the status line is a single mark', async ($, on) => {
  const opened: string[] = []
  const status: (string | undefined)[] = []
  project(on, '/p', PANEL_JSON)
  on('session.surfaces', () => ({ value: [] }))
  on('ui.status', (_: any, e: any) => { status.push(e.text); return { value: undefined } })
  on('ui.open', (_: any, e: any) => { opened.push(e.id); return { value: { isPlaced: false } } })
  await $.session.start({ cwd: '/p', surface: null, isInteractive: true })
  expect(opened).toEqual([])
  expect(status).toEqual(['✓'])
})

test('falls back to /usr/bin/python3 when python3 is not on PATH', async ($, on) => {
  const calls = project(on, '/p', EXTRA, '{"compact": "summary"}', true)
  const r: any = await $.session.compact({ trigger: 'auto', messages: [{ role: 'user', text: 'old conversation', toolUses: [] }] } as any)
  expect(r.messages.length).toBe(2)
  expect(calls.some(a => a[0] === '/usr/bin/python3')).toBe(true)
})

// Records the model each Agent call reaches the engine with.
function agentSpy(on: any) {
  const seen: (string | undefined)[] = []
  on('tool.call', (_: any, e: any) => { seen.push(e.model); return { result: 'ok' } })
  return seen
}

test('Explore subagents run on Haiku; other agents and explicit models stay', async ($, on) => {
  project(on, '/p', '')
  const seen = agentSpy(on)
  await $.tool.call({ tool: 'Agent', description: 'find x', prompt: 'find x', subagent_type: 'Explore' } as any)
  await $.tool.call({ tool: 'Agent', description: 'do y', prompt: 'do y', subagent_type: 'general-purpose' } as any)
  await $.tool.call({ tool: 'Agent', description: 'find z', prompt: 'find z', subagent_type: 'Explore', model: 'opus' } as any)
  expect(seen).toEqual(['haiku', undefined, 'opus'])
})

test('exploreModel "" leaves Explore untouched', async ($, on) => {
  project(on, '/p', '', '{"exploreModel": ""}')
  const seen = agentSpy(on)
  await $.tool.call({ tool: 'Agent', description: 'find x', prompt: 'find x', subagent_type: 'Explore' } as any)
  expect(seen).toEqual([undefined])
})

test('Explore and other look-up subagents go to the cheap model, general-purpose stays', async ($, on) => {
  project(on, '/p', '')
  const seen: any[] = []
  on('tool.call', (_: any, e: any) => { seen.push(e); return { result: 'ok' } })
  await $.tool.call({ tool: 'Agent', subagent_type: 'claude-code-guide', prompt: 'x', description: 'x' } as any)
  await $.tool.call({ tool: 'Agent', subagent_type: 'general-purpose', prompt: 'x', description: 'x' } as any)
  expect(seen.map(e => e.model)).toEqual(['haiku', undefined])
})
