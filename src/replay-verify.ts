/**
 * JevLoop · **验证一条决策记录**（格式见 `replay-schema.ts`）
 *
 * 从 `replay-schema.ts` 拆出来 —— 那个文件是「一条记录长什么样、怎么从事件里读
 * 出来」，这里是「一条记录能被查出什么」。两件事**各有各的变化理由**：格式随
 * 事件字段变，检查随我们能证明什么变。塞在一个文件里时它到了 332 行，
 * `npm run check` 的 file-focus 报了出来。
 *
 * ── 四项检查，四档结论 ────────────────────────────────────────
 *
 * `verified` / `partial` / `unverifiable` / `mismatch` —— **四档而不是两档**，
 * 因为「查不了」和「查过且通过」是两个不同的答案。把前者算成后者，一份缺字段的
 * 旧日志就会被读成「干净」。
 *
 * ★★ **合并判定那一档是最难的，也是第一版写错的地方。** 详见下面 `sent-frame`。
 *
 * @module JevLoop/replay-verify
 */

import { frameDigest, requestDigest } from './frame-digest.ts'
import { REPLAY_NOTES, type ReplayRecord } from './replay-schema.ts'

/** 一条记录的结论。**四档，不是两档** —— 「无法验证」和「验证通过」必须分开 */
export type ReplayStatus =
  /** 该做的检查都做了，全部通过 */
  | 'verified'
  /** 做了一部分检查并通过；其余**说清为什么做不了** */
  | 'partial'
  /** 记录里缺重放必需的字段（旧日志、或手写漏了）—— 一条检查都没法做 */
  | 'unverifiable'
  /** 有检查**没通过** —— 记录不自洽 */
  | 'mismatch'

export interface ReplayCheck {
  /** 这项在查什么 */
  what: string
  outcome: 'pass' | 'fail' | 'skipped'
  /** 失败说差在哪；跳过说为什么 */
  detail: string
}

export interface ReplayVerdict {
  status: ReplayStatus
  checks: ReplayCheck[]
  /**
   * **这一层验证不了什么。** 逐条写出来，因为「可重放」最容易被读成
   * 「可复现」或「可判对错」，而这两件事它都给不了。
   */
  notes: string[]
}

/**
 * 验证一条记录是否自洽 —— 四项检查，四档结论（见 `ReplayStatus`）。
 *
 *     frame-solo      单节点：`state` 能否重算出该节点自己的 `frame.digest`
 *     sent-frame      **两者都查**：送出去的那份帧能否从记录重算
 *                     （单节点 = 该节点的帧；合并 = `frameDigest(batchIds.join('+'), state)`）
 *     questions-solo  单节点：`questions` 必须等于 `sentQuestions`
 *     request         `requestDigest(sentFrameDigest, sentQuestions)` 能否重算
 *
 * ★ 「查不了」要**明说**（`outcome: 'skipped'` + 为什么），不能算通过：
 *   一份缺字段的旧日志必须得到 `unverifiable`，而不是看起来干净。
 *
 * ★ 合并判定里**每个节点自己那份帧**重不了（它的帧对应的 state 没落盘），
 *   但**合成帧**能 —— 后半句是第一版漏掉的，代价是把合并记录的 `state` 改掉
 *   之后重放照样报通过。
 */
export function verifyRecord(rec: ReplayRecord): ReplayVerdict {
  const checks: ReplayCheck[] = []
  const merged = rec.batchIds.length > 1

  // ① 节点自己那份帧 —— 只有单节点时能从这条记录重算
  if (merged) {
    checks.push({
      what: 'frame-solo',
      outcome: 'skipped',
      detail:
        `这是一次**合并**判定（${rec.batchIds.join(' + ')}）：记录里的 state 是合并帧，` +
        '所以每个节点自己那份帧没法从这一条记录重导',
    })
  } else if (rec.frameDigest === undefined) {
    checks.push({ what: 'frame-solo', outcome: 'skipped', detail: '记录里没有 frameDigest（这个节点没声明帧）' })
  } else {
    const recomputed = frameDigest(rec.node, rec.state)
    checks.push({
      what: 'frame-solo',
      outcome: recomputed === rec.frameDigest ? 'pass' : 'fail',
      detail:
        recomputed === rec.frameDigest
          ? `state 重算出 ${recomputed}`
          : `记录说 ${rec.frameDigest}，而 state 重算出 ${recomputed} —— 记录不自洽`,
    })
  }

  /*
    ② 单节点时「这个节点被问的」和「实际发出去的」必须是同一份。

    ★ 合并时两者**本来就不同**（前者是节点自己那份、后者是并集），所以这一项
      只在单节点时检查。而它值得单列：`requestDigest` 覆盖的是 `sentQuestions`，
      所以单节点记录里被人改过的 `questions` 不会被请求指纹抓到 —— 这一项就是
      补那个洞的。
  */
  if (!merged) {
    /*
      ★ 两边都空时**跳过**，不报 pass。空对象等于空对象这件事什么都没验证 ——
        让它算一项通过，一个**什么字段都没有**的裸记录就会从「无法重放」
        变成「部分通过」，而那是把「没查」说成了「查过了」。
        （第一版就是这么错的：裸记录的结论是 partial。）
    */
    const empty = Object.keys(rec.questions).length === 0 && Object.keys(rec.sentQuestions).length === 0
    const same = JSON.stringify(rec.questions) === JSON.stringify(rec.sentQuestions)
    checks.push({
      what: 'questions-solo',
      outcome: empty ? 'skipped' : same ? 'pass' : 'fail',
      detail: empty
        ? '记录里一个问题都没有 —— 无可比对，跳过（不算通过）'
        : same
          ? '单节点：被问的就是发出去的'
          : '单节点时 questions 必须等于 sentQuestions —— 两者不同说明记录被动过',
    })
  }

  // ③ 送出去的那份帧
  if (rec.sentFrameDigest === undefined) {
    checks.push({
      what: 'sent-frame',
      outcome: 'skipped',
      detail: '记录里没有 sentFrameDigest（旧日志，或不是本实现写的）—— 请求指纹也无从重算',
    })
  } else if (merged) {
    /*
      ★★ 合并这一档**也能重算**，第一版我写错了。

      当时写的是「无法从单条记录复算」—— 错的。合并帧的指纹就是
      `frameDigest(batchIds.join('+'), state)`，而**两者记录里都有**：
      `batchIds` 是参与合并的节点，`state` 就是那份合成帧（事件就是这么填的）。

      代价实测过：漏掉这一项之后，把一条合并记录的 `state` 改掉，
      `npm run replay` **照样报 0 mismatch、退出码 0** —— 而那正是重放要抓的
      东西。所以这一项不是锦上添花，是漏洞。
    */
    const recomputed = frameDigest(rec.batchIds.join('+'), rec.state)
    checks.push({
      what: 'sent-frame',
      outcome: recomputed === rec.sentFrameDigest ? 'pass' : 'fail',
      detail:
        recomputed === rec.sentFrameDigest
          ? `合成帧（${rec.batchIds.join(' + ')}）重算出 ${recomputed}`
          : `记录说 ${rec.sentFrameDigest}，而合成帧重算出 ${recomputed} —— 记录不自洽`,
    })
  } else {
    const ok = rec.frameDigest === undefined || rec.sentFrameDigest === rec.frameDigest
    checks.push({
      what: 'sent-frame',
      outcome: ok ? 'pass' : 'fail',
      detail: ok
        ? '单节点：送出去的就是这个节点自己的帧'
        : `单节点时两者必须相等，而 frameDigest=${rec.frameDigest} · sentFrameDigest=${rec.sentFrameDigest}`,
    })
  }

  // ④ 请求指纹
  if (rec.sentFrameDigest === undefined || rec.requestDigest === undefined) {
    checks.push({
      what: 'request',
      outcome: 'skipped',
      detail: '缺 sentFrameDigest 或 requestDigest —— 无法回答「这是不是同一个请求」',
    })
  } else {
    const recomputed = requestDigest(rec.sentFrameDigest, rec.sentQuestions)
    checks.push({
      what: 'request',
      outcome: recomputed === rec.requestDigest ? 'pass' : 'fail',
      detail:
        recomputed === rec.requestDigest
          ? `sentFrameDigest + sentQuestions 重算出 ${recomputed}`
          : `记录说 ${rec.requestDigest}，而重算出 ${recomputed} —— 问题集或帧被动过`,
    })
  }

  const failed = checks.some((c) => c.outcome === 'fail')
  const passed = checks.filter((c) => c.outcome === 'pass').length
  const skipped = checks.filter((c) => c.outcome === 'skipped').length

  const status: ReplayStatus = failed
    ? 'mismatch'
    : passed === 0
      ? 'unverifiable'
      : skipped > 0
        ? 'partial'
        : 'verified'

  return { status, checks, notes: [...REPLAY_NOTES] }
}
