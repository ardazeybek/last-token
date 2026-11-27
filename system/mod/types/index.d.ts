// State contract of the last-token mod: what the savings pane and the digest row read.
export type Savings = {
  requests: number      // main-thread API calls of the session
  sent: number          // input tokens actually sent
  saved: number         // input tokens early compaction kept out (vs. native compaction alone)
  compactions: number   // early compactions
  deterministic: number // ... of them without a summarizer call
  context: number       // context of the last call
  pct: number           // saved / (saved + sent), %
  quota: number         // plan quota this session used (main + subagents), % of a 5-hour window
  quota_sub: number     // ... of it by subagents
  quota_saved: number   // quota early compaction saved, same unit
  quota_pct: number     // quota_saved / (quota_saved + quota), %
  new_chat?: { ctx: number; base: number; pct: number }  // per-request saving of a fresh chat (0 = keep going)
  model: string         // main-thread model
  measured: boolean     // false = weights scaled from Haiku by API price (not measured)
  mode: 'project' | 'global' | 'off' // where the memory lives
  label: string         // project name or folder
  store: string         // .ctx folder in use
  checks: Check[]       // health of each part (hooks, trigger)
  cache?: CacheHealth   // prompt-cache re-writes (ctx.py cache_report)
}

export type Bust = { n: number; tokens: number }
export type CacheHealth = {
  busts: { idle?: Bust; prefix?: Bust; model?: Bust }  // re-writes by cause: idle > TTL, changed prefix, model switch
  idle_compactions: number  // compactions made right after the cache went cold
  bust_quota?: number       // quota points those re-writes cost
}

// Cold-cache pruning this session: tool outputs replaced by a stub, and their estimated tokens.
export type Pruned = { outputs: number; tokens: number }

export type Check = { name: string; ok: boolean; detail: string }

declare module 'claude-code' {
  interface PluginState {
    'last-token': { savings: Savings | null; shownDigests: string[]; pruned: Pruned }
  }
}
