// last-token mod: deterministic (no-LLM) compaction from .ctx/ctx.py, the digest row folded, rarely used
// tools deferred, Explore subagents on a cheaper model, and the session's plan-quota savings live
// (pane + status line). Active in projects with .ctx/ctx.py and (global mode) everywhere else;
// each lever is set in .ctx/mod.json (global: ~/.claude/last-token/mod.json).
import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Savings } from '../types'

const DEFAULTS = {
  deferTools: ['ScheduleWakeup', 'ReportFindings', 'ListAgents', 'CronCreate', 'RemoteTrigger', 'NotebookEdit'],
  // 'digest' = no summarizer call, ctx.py's deterministic digest only (cheapest in plan quota, default);
  // 'summary' = the model's own summary + the person's words and task list verbatim (+57 % quota); 'native' = untouched.
  compact: 'digest' as 'summary' | 'digest' | 'native' | boolean,
  recentChars: 6000,        // newest steps shown in full inside the digest
  exploreModel: 'haiku' as '' | 'haiku' | 'sonnet',  // model for read-only subagents (cheapAgents); '' = untouched
  cheapAgents: ['Explore', 'claude-code-guide', 'statusline-setup'],  // subagent types that only search/read/look up
  // Cold-cache pruning: on the first model request after a gap longer than the cache TTL (the whole
  // context is re-written then anyway), old big tool outputs are replaced by a one-line stub, and the
  // same stubs are applied to every later request so the cached prefix stays identical. false = off.
  coldPrune: true,
  coldDigest: true,        // after a cold gap, history before the new prompt → ctx.py digest (request only; the UI keeps it all)
  coldDigestMinChars: 80000, // only when that history is at least this big
  coldSeconds: 3630,        // gap that counts as a cold cache (TTL 1 h + margin)
  pruneKeepTurns: 3,        // tool outputs of the newest N user prompts stay whole
  pruneMinChars: 1500,      // smaller tool outputs stay whole
  panel: false,             // developer view: open the savings pane at session start + numbers in the status line
  statusLine: false,        // plain-text status line; off: the band above the prompt already says it
  debug: false,             // one line per event in ~/.claude/last-token/mod.log
}

// First words of the digest ctx.py compact-summary prints; used to spot its row.
const DIGEST_HEAD = '[last-token compaction:'
const PANE = 'last-token-savings'
const PANE_TITLE = 'Quota savings'

const pruned = atom({ plugin: 'last-token', key: 'pruned' } as const, { outputs: 0, tokens: 0 })

// FNV-1a hash of a string, as 8 hex digits (conversation key for the pruning store).
export function hash(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return h.toString(16).padStart(8, '0')
}

// Characters a tool_result's content carries (an image counts as ~6K chars, ~1.5K tokens).
function resultChars(content: unknown): number {
  if (typeof content === 'string') return content.length
  if (!Array.isArray(content)) return 0
  return content.reduce((n, b: any) => n + (b?.type === 'text' ? String(b.text ?? '').length : b?.type === 'image' ? 6000 : 0), 0)
}

// Index of the first message whose tool outputs stay whole: the Nth-newest real user prompt.
function keepFrom(msgs: any[], keepTurns: number): number {
  let seen = 0
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (m?.role !== 'user') continue
    const blocks = typeof m.content === 'string' ? [{ type: 'text' }] : Array.isArray(m.content) ? m.content : []
    if (blocks.some((b: any) => b?.type === 'text') && ++seen >= keepTurns) return i
  }
  return 0
}

type ColdCut = { n: number; head: string; digest: string }
type PruneState = { t: number; ids: string[]; cut?: ColdCut }

// True when the gap since the last request means the prompt cache has expired.
function isCold(st: PruneState, now: number, coldSeconds: number): boolean {
  return !!st.t && now - st.t > coldSeconds * 1000
}

// Index of the newest user message that is a typed prompt (no tool results), or -1.
export function lastPrompt(msgs: any[]): number {
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (m?.role !== 'user') continue
    const blocks = Array.isArray(m.content) ? m.content : []
    return blocks.some((b: any) => b?.type === 'tool_result') ? -1 : i
  }
  return -1
}

// Messages before index n replaced by one digest text block in front of message n; null = the cut no longer fits.
export function applyCut(msgs: any[], cut: ColdCut): any[] | null {
  const m = msgs[cut.n]
  if (!m || m.role !== 'user' || hash(JSON.stringify(m.content)) !== cut.head) return null
  const blocks = typeof m.content === 'string' ? [{ type: 'text', text: m.content }] : m.content
  return [{ ...m, content: [{ type: 'text', text: cut.digest }, ...blocks] }, ...msgs.slice(cut.n + 1)]
}

// Characters of message content before index n (a cheap size estimate).
function charsBefore(msgs: any[], n: number): number {
  let s = 0
  for (let i = 0; i < n; i++) s += JSON.stringify(msgs[i]?.content ?? '').length
  return s
}
const PRUNE_KEYS = 'prune:index'  // conversation keys, oldest first (bounded)
const PRUNE_MAX_CONVS = 150

// Rewrite one engine request body: pick new stubs when the cache went cold, apply all stubs; null = untouched.
export function pruneBody(req: any, st: PruneState, now: number, c: { coldSeconds: number; pruneKeepTurns: number; pruneMinChars: number }):
    { body: any; st: PruneState; added: number; tokens: number } | null {
  const msgs = req?.messages
  if (!Array.isArray(msgs) || msgs.length < 3) return null
  const ids = new Set(st.ids)
  let added = 0, tokens = 0
  if (st.t && now - st.t > c.coldSeconds * 1000) {
    const until = keepFrom(msgs, c.pruneKeepTurns)
    for (let i = 0; i < until; i++) {
      const blocks = msgs[i]?.role === 'user' && Array.isArray(msgs[i].content) ? msgs[i].content : []
      for (const b of blocks) {
        if (b?.type !== 'tool_result' || !b.tool_use_id || ids.has(b.tool_use_id)) continue
        const n = resultChars(b.content)
        if (n < c.pruneMinChars) continue
        ids.add(b.tool_use_id); added++; tokens += Math.round(n / 4)
      }
    }
  }
  if (!ids.size) return { body: null, st: { t: now, ids: st.ids }, added, tokens }
  let changed = false
  const out = msgs.map((m: any) => {
    if (m?.role !== 'user' || !Array.isArray(m.content) || !m.content.some((b: any) => b?.type === 'tool_result' && ids.has(b.tool_use_id))) return m
    changed = true
    return { ...m, content: m.content.map((b: any) => b?.type === 'tool_result' && ids.has(b.tool_use_id)
      ? { ...b, content: `[last-token: this tool output (~${Math.round(resultChars(b.content) / 4)} tokens) was dropped after a long break to save plan quota; run the tool again if you need it]` }
      : b) }
  })
  return { body: changed ? { ...req, messages: out } : null, st: { t: now, ids: [...ids] }, added, tokens }
}

const savings = atom({ plugin: 'last-token', key: 'savings' } as const, null)
const shownDigests = atom({ plugin: 'last-token', key: 'shownDigests' } as const, [])

type Config = typeof DEFAULTS & { ctxPy: string; root: string; mode: 'project' | 'global' }

// The desktop app starts sessions in a pre-warmed placeholder folder and moves them to the real one later.
const isSpare = (dir: string) => `${dir}/`.includes('/.claude/spares/')

// Nearest folder at or above dir holding a project .ctx/ctx.py, or null.
async function findProject($: any, dir: string): Promise<string | null> {
  let cur = dir.replace(/\/+$/, '') || '/'
  for (;;) {
    if (await $.fs.exists(`${cur}/.ctx/ctx.py`).catch(() => false)) return cur
    if (cur === '/' || !cur.includes('/')) return null
    cur = cur.slice(0, cur.lastIndexOf('/')) || '/'
  }
}

// True when the folder or a parent holds a `.no-last-token` file (global mode stays out of it).
async function optedOut($: any, dir: string): Promise<boolean> {
  let cur = dir.replace(/\/+$/, '') || '/'
  for (;;) {
    if (await $.fs.exists(`${cur}/.no-last-token`).catch(() => false)) return true
    if (cur === '/' || !cur.includes('/')) return false
    cur = cur.slice(0, cur.lastIndexOf('/')) || '/'
  }
}

// Global mode is on when ~/.claude/last-token/global.json (beside this installed mod) says so.
async function globalHome($: any): Promise<string | null> {
  const home = $.plugin.root.replace(/\/mod\/?$/, '')
  if (home === $.plugin.root) return null
  try {
    const flag = JSON.parse(await $.fs.read(`${home}/global.json`))
    return flag?.enabled && (await $.fs.exists(`${home}/ctx.py`)) ? home : null
  } catch {
    return null
  }
}

// Settings for this session's folder: a last-token project, global mode, or null (last-token off here).
// Cached per folder, never for the desktop's placeholder folder: the session moves out of it.
const cached = new Map<string, Promise<Config | null>>()
async function config($: any): Promise<Config | null> {
  let root: string
  try { root = await $.session.root() } catch { return null }
  if (!root || isSpare(root)) return null
  if (!cached.has(root)) cached.set(root, resolveConfig($, root))
  return cached.get(root)!
}

// Read the folder's mode and its mod.json (defaults first, then the file's own values).
async function resolveConfig($: any, root: string): Promise<Config | null> {
  try {
    const proj = await findProject($, root)
    const home = proj || (await optedOut($, root)) ? null : await globalHome($)
    if (!proj && !home) return null
    const own = proj ? `${proj}/.ctx/mod.json` : `${home}/mod.json`
    let extra: Record<string, unknown> = {}
    try { extra = JSON.parse(await $.fs.read(own)) } catch { extra = {} }
    const ctxPy = proj ? `${proj}/.ctx/ctx.py` : `${home}/ctx.py`
    return { ...DEFAULTS, ...extra, ctxPy, root, mode: proj ? 'project' : 'global' } as Config
  } catch {
    return null
  }
}

// Compaction mode of a config ('summary' | 'digest' | 'native'); old boolean values map onto it.
function compactMode(c: Config): 'summary' | 'digest' | 'native' {
  if (c.compact === false) return 'native'
  if (c.compact === true) return 'summary'
  return c.compact
}

// Python interpreters to try: some desktop sessions start without /usr/bin on PATH (ENOENT on 'python3').
const PYTHONS = ['python3', '/usr/bin/python3', '/usr/local/bin/python3', '/opt/homebrew/bin/python3']
let python = PYTHONS[0]

// Run ctx.py; when it cannot be started (any error but a timeout), retry with the next known path and remember the one that works.
async function runCtx($: any, c: Config, args: string[], opts: any): Promise<any> {
  let last: unknown
  for (const py of [python, ...PYTHONS.filter(p => p !== python)]) {
    try {
      const r = await $.process.run([py, c.ctxPy, '--at', c.root, ...args], opts)
      python = py
      return r
    } catch (err) { last = err; if (/time(d)? ?out/i.test(String(err))) throw err }
  }
  throw last
}

// 4.215.145 → "4,2M", 93.594 → "94K" (Turkish decimal comma).
export function fmtTokens(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `${Math.round(n / 1e3)}K`
  return String(Math.max(0, Math.round(n)))
}

// Quota points (% of a 5-hour window) → "0,42" (Turkish decimal comma, 2 digits under 10).
export function fmtQuota(p: number): string {
  const v = Math.max(0, p)
  return (v >= 10 ? v.toFixed(0) : v.toFixed(2))
}

// Diagnostics (mod.json `debug: true`): append one line to ~/.claude/last-token/mod.log.
async function dbg($: any, c: Config | null, msg: string): Promise<void> {
  if (!c?.debug) return
  try { await $.process.run(['sh', '-c', 'printf "%s\n" "$1" >> "$HOME/.claude/last-token/mod.log"', 'x', `${new Date().toISOString()} ${msg}`], { timeoutMs: 3000 }) } catch {}
}

// Sessions whose savings pane was already opened once (never reopened against the user's close).
const paneOpened = new Set<string>()

// Open the pane once per session. Unseated, ui.open waits for a surface: the desktop app often
// never shows up in surfaces(), so waiting for one there meant the pane never opened.
async function openPaneOnce($: any, c: Config): Promise<void> {
  if (!c.panel) return
  const id = await $.session.id()
  if (paneOpened.has(id)) return
  paneOpened.add(id)
  try {
    const r = await $.ui.open({ id: PANE, title: PANE_TITLE })
    await dbg($, c, `pane open sid=${id} placed=${r?.isPlaced} ${r?.reason ?? ''}`)
  } catch (err) { paneOpened.delete(id); await dbg($, c, `pane open error ${String(err).slice(0, 200)}`) }
}

// Re-read savings + health from ctx.py and refresh the status line.
async function refresh($: any, c: Config): Promise<void> {
  try {
    const run = await runCtx($, c, ['panel', '--session', await $.session.id()], { cwd: c.root, timeoutMs: 15000 })
    await dbg($, c, `refresh sid=${await $.session.id()} root=${c.root} exit=${run.exitCode} surfaces=${JSON.stringify(await $.session.surfaces())} err=${String(run.stderr ?? '').slice(0, 200)}`)
    if (run.exitCode !== 0) return
    const s = JSON.parse(run.stdout) as Savings
    if (typeof s.saved !== 'number') return
    await update($, savings, () => s)
    await openPaneOnce($, c)
    if (c.statusLine) {
      const warn = (s.checks ?? []).some(k => !k.ok) ? ' ⚠' : ''
      const pct = s.quota_pct ?? 0
      // Plain-text fallback (the status line has no colors); the coloured line is the AbovePrompt band.
      $.ui.status(`Active${warn}${pct > 0 ? ` −${pct}%` : ''}${s.new_chat?.pct ? ' · new chat cheaper' : ''}`)
    }
  } catch (err) { await dbg($, c, `refresh error ${String(err).slice(0, 200)}`) }
}

// Pane rows about the prompt cache: re-writes by cause and cold-cache compactions.
// Quota points of tokens that a cold cache would have re-written (Haiku-measured weight × model factor).
export function pruneQuota(tokens: number, model: string): number {
  const m = (model ?? '').toLowerCase()
  const mul = m.includes('opus') || m.includes('fable') ? 5 : m.includes('sonnet') ? 3 : 1
  return tokens * 4.6e-6 * mul
}

export function cacheLines(s: Savings): { text: string; dim: boolean }[] {
  const c = s.cache
  if (!c) return []
  const b = c.busts ?? {}
  const parts = [
    b.idle?.n ? `${b.idle.n} long pause(s)` : '',
    b.prefix?.n ? `${b.prefix.n} prefix change(s)` : '',
    b.model?.n ? `${b.model.n} model switch(es)` : '',
  ].filter(Boolean)
  const out = [{ text: parts.length ? `Cache rewritten from scratch: ${parts.join(', ')} (~${fmtQuota(c.bust_quota ?? 0)} pts)` : 'No cache busts ✓', dim: !parts.length }]
  if (c.idle_compactions) out.push({ text: `Compactions after a pause: ${c.idle_compactions} (cold cache rewritten small)`, dim: false })
  return out
}

export const register: Register = on => {
  // Open the savings pane and offer /lt-savings in last-token projects.
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await $.command.register({ name: 'lt-savings', description: 'last-token: open the developer quota pane' })
    const c = await config($)  // null while the desktop still has the session in its placeholder folder
    await dbg($, c, `start root=${await $.session.root()} config=${c ? c.mode : 'null'}`)
    if (c) await refresh($, c)  // opens the pane
    return r
  })

  // A client that joins later (desktop, phone) gets the pane too.
  on('session.attach', async ($, e, next) => {
    const r = await next(e)
    const c = await config($)
    if (c) await refresh($, c)
    return r
  })

  on('command.run', { command: 'lt-savings' }, async $ => {
    const c = await config($)
    if (!c) return { text: 'Last Token is off in this folder (no project install and no global mode).' }
    await refresh($, c)
    await $.ui.open({ id: PANE, title: PANE_TITLE, focus: true })
    return { text: 'Quota savings pane opened.' }
  })

  // Big, rarely used tools wait behind ToolSearch (their schema loads when asked for by name).
  on('tool.describe', async ($, e, next) => {
    const r = await next(e)
    const c = await config($)
    if (!c || !c.deferTools.includes(e.tool) || r.isDeferred) return r
    return { ...r, isDeferred: true }
  })

  // Explore subagents only search and read: a cheaper model does that as well, and every
  // subagent re-writes a ~36K base plus all it reads into the cache (the costliest token type).
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    const c = await config($)
    if (!c || !c.exploreModel || e.model || !c.cheapAgents.includes(e.subagent_type ?? '')) return next(e)
    await dbg($, c, `${e.subagent_type} → ${c.exploreModel}`)
    return next({ ...e, model: c.exploreModel })
  }).catch(($, e, next) => next(e))

  // Cold-cache pruning of engine model requests (see DEFAULTS.coldPrune). Any failure: the request goes on as built.
  on('http.fetch', async ($, e, next) => {
    const init: any = e.init
    if ((next as any).origin?.plugin !== 'engine' || init?.method !== 'POST' || typeof init?.body !== 'string'
        || !/\/v1\/messages(\?|$)/.test(e.url)) return next(e)
    const c = await config($)
    if (!c || !c.coldPrune) return next(e)
    const req = JSON.parse(init.body)
    if (!Array.isArray(req?.messages) || !req.messages.length) return next(e)
    const key = `prune:${hash(JSON.stringify(req.messages[0]?.content ?? '').slice(0, 4000))}`
    const st = ((await $.store.get(key)) as PruneState | undefined) ?? { t: 0, ids: [] }
    const now = await $.clock.now()
    // Cold digest: the whole context is re-written now anyway, so re-write a digest instead of the history.
    if (c.coldDigest && req.messages.length >= 3 && isCold(st, now, c.coldSeconds)) {
      const n = lastPrompt(req.messages)
      if (n > 0 && charsBefore(req.messages, n) >= c.coldDigestMinChars) {
        const run = await runCtx($, c, ['compact-summary'], {
          cwd: c.root, timeoutMs: 20000, env: { CTX_RECENT_CHARS: String(c.recentChars) },
          stdin: JSON.stringify({ session_id: await $.session.id(), cwd: c.root, trigger: 'cold' }),
        }).catch(() => null)
        const digest = run?.exitCode === 0 ? String(run.stdout).trim() : ''
        if (digest.startsWith(DIGEST_HEAD)) {
          st.cut = { n, head: hash(JSON.stringify(req.messages[n].content)), digest }
          st.ids = []
          await dbg($, c, `cold digest ${key}: ${n} messages → ${digest.length} chars`)
        }
      }
    }
    if (st.cut) {
      const cut = applyCut(req.messages, st.cut)
      if (cut) req.messages = cut; else delete st.cut  // rewound before the cut or a new history
    }
    const r = pruneBody(req, st, now, c) ?? (st.cut ? { body: null, st: { t: now, ids: st.ids }, added: 0, tokens: 0 } : null)
    if (!r) return next(e)
    if (st.cut) { r.st.cut = st.cut; if (!r.body) r.body = req }
    await $.store.set(key, r.st)
    if (!st.t) {  // a new conversation: remember its key, forget the oldest beyond the bound
      const keys = (((await $.store.get(PRUNE_KEYS)) as string[] | undefined) ?? []).filter(k => k !== key)
      keys.push(key)
      for (const old of keys.splice(0, Math.max(0, keys.length - PRUNE_MAX_CONVS))) await $.store.delete(old)
      await $.store.set(PRUNE_KEYS, keys)
    }
    if (r.added) {
      await update($, pruned, p => ({ outputs: p.outputs + r.added, tokens: p.tokens + r.tokens }))
      await dbg($, c, `cold prune ${key}: +${r.added} outputs, ~${r.tokens} tokens`)
    }
    return r.body ? next({ ...e, init: { ...init, body: JSON.stringify(r.body) } }) : next(e)
  }).catch(($, e, next) => next(e))

  // Figures are re-read once per turn (no timer, nothing while idle).
  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    const c = await config($)
    if (c) await refresh($, c)
    return r
  })

  // Compaction. 'summary': the engine's own summary, then the person's words + task list verbatim from
  // ctx.py (the PreCompact hook archives the segment). 'digest': no summarizer call, ctx.py's digest only.
  on('session.compact', async ($, e, next) => {
    if (e.agentId || e.instructions) return next(e)
    const c = await config($)
    const mode = c ? compactMode(c) : 'native'
    if (!c || mode === 'native') return next(e)
    if (mode === 'digest' && e.trigger === 'precompute') return { skip: 'last-token: deterministic compaction' }
    const ask = async (...args: string[]) => {
      const run = await runCtx($, c, ['compact-summary', ...args], {
        cwd: c.root,
        stdin: JSON.stringify({ session_id: await $.session.id(), cwd: c.root, trigger: e.trigger }),
        env: { CTX_RECENT_CHARS: String(c.recentChars) },
        timeoutMs: 20000,
      })
      return run.exitCode === 0 ? run.stdout.trim() : ''
    }
    if (mode === 'summary') {
      const r = await next(e)
      // Ahead-of-time work stays untouched: the block is added when the compaction really happens.
      if (e.trigger === 'precompute' || !('messages' in r)) return r
      const extra = await ask('--extra').catch(() => '')
      return extra ? { ...r, messages: [...r.messages, { role: 'user', text: extra, toolUses: [] }] } : r
    }
    const digest = await ask()
    if (!digest.startsWith(DIGEST_HEAD)) return next(e)  // ctx.py failed, paused or printed something else
    // Only the digest: kept old messages would stay chained to the old history and come back on --resume.
    return { messages: [{ role: 'user', text: digest, toolUses: [] }] }
  }).catch(($, e, next) => next(e))

  // The digest is a user-role row for the model; people see one dim line, not "a message they sent".
  // Terminal: ctrl+o (isExpanded) shows it whole. Other surfaces have no ctrl+o and always pass
  // isExpanded, so they get a show/hide button instead.
  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const text: string = e.props?.text ?? ''
    // Only our own rows: the digest/extra always names its archive log or folder.
    if (!text.startsWith(DIGEST_HEAD) || !/\.ctx\/archive\//.test(text)) return next(e)
    const log = /archive\/(L\d+)-log/.exec(text)?.[1] ?? 'digest'
    const line = `↻ Context compacted${log !== 'digest' ? ` (${log})` : ''} — not your message; older steps are archived, work continues.`
    const { Box, Text, Button } = $.ui.resolve(e)
    if (e.surface === 'terminal') {
      return e.props?.isExpanded ? next(e) : <Text dimColor>{line}</Text>
    }
    const isShown = (await read($, shownDigests)).includes(log)
    const toggle = () => update($, shownDigests, l => (l.includes(log) ? l.filter(x => x !== log) : [...l, log].slice(-20)))
    return (
      <Box flexDirection="column">
        <Box>
          <Text dimColor>{line} </Text>
          <Button key={`digest-${log}`} plain label={isShown ? 'Hide summary' : 'Show summary'} onPress={toggle} />
        </Box>
        {isShown && <Text dimColor>{text}</Text>}
      </Box>
    )
  }).catch(($, e, next) => next(e))

  // Band above the prompt: green "Last Token Active −N%", red line when a fresh chat would be cheaper.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const s = await read($, savings)
    if (!s || (e as any).hasSurvey) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const pct = s.quota_pct ?? 0
    const nc = s.new_chat?.pct ?? 0
    return (
      <Box flexDirection="column">
        <Text><Text color="green" bold>Last Token Active</Text>{pct > 0 ? <Text color="green">{`  −${pct}% quota`}</Text> : null}</Text>
        {nc > 0 ? <Text color="red">{`This chat is long. Starting a new chat for your next task uses about ${nc}% less quota per message.`}</Text> : null}
      </Box>
    )
  })

  // The pane is the "last-token works here" sign: it opens only where last-token is active.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const s = await read($, savings)
    const p = await read($, pruned)
    if (!s) return <Text dimColor>Last Token is running. Numbers appear after the first reply.</Text>
    const checks = s.checks ?? []
    const bad = checks.filter(k => !k.ok)
    const where = s.mode === 'project' ? `Project: ${s.label ?? ''}` : `Global mode: ${s.label ?? ''}`
    const q = s.quota ?? 0
    return (
      <Box flexDirection="column">
        <Text color={bad.length ? 'warning' : 'success'} bold>{bad.length ? '⚠ Last Token is partly working' : '✓ Last Token is active in this session'}</Text>
        <Text dimColor>{where}</Text>
        <Text> </Text>
        <Text bold>{`Quota saved: −${fmtQuota(s.quota_saved ?? 0)} pts  (${s.quota_pct ?? 0}% less)`}</Text>
        <Text>{`This session used: ~${fmtQuota(q)} pts${(s.quota_sub ?? 0) > 0 ? ` (subagents ${fmtQuota(s.quota_sub)})` : ''}`}</Text>
        <Text dimColor>1 pt = 1% of the 5-hour window (measured on the Pro plan)</Text>
        <Text> </Text>
        {cacheLines(s).map(l => <Text dimColor={l.dim}>{l.text}</Text>)}
        {p.outputs > 0 && <Text>{`Old outputs pruned after a pause: ${p.outputs} (~${fmtTokens(p.tokens)} tokens, ~${fmtQuota(pruneQuota(p.tokens, s.model))} pts)`}</Text>}
        <Text>{`Compactions: ${s.compactions} (${s.deterministic} without a model) · ${s.requests} requests`}</Text>
        <Text>{`Context not re-read: −${fmtTokens(s.saved)} tokens · current context ${fmtTokens(s.context)}`}</Text>
        <Text> </Text>
        {checks.map(k => (
          <Text color={k.ok ? undefined : 'error'} dimColor={k.ok}>{`${k.ok ? '✓' : '✗'} ${k.name}${k.detail ? ` — ${k.detail}` : ''}`}</Text>
        ))}
        <Text dimColor>{`Estimate vs. Claude Code's own compaction${s.measured === false ? '; non-Haiku weights come from API price ratios' : ''}. Updated after every reply.`}</Text>
      </Box>
    )
  })
}
