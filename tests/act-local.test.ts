/**
 * 破坏性工具（`delete_file`）—— TODO §1 的第一刀。
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件测的不是「能不能删文件」，是**删除有没有被真的拦住**
 * ═══════════════════════════════════════════════════════════
 *
 * §1 的原话是「风险阶梯要有真东西可爬」。四个工具里最危险的只是写文件，
 * 于是 `grade_risk` 的第 4 档（destructive）**从来没有被真的走到过** ——
 * 一条没人爬过的梯子，说它拦得住什么都是空的。
 *
 * 所以这里的验收是**反向的**：不是「删成功了」，而是
 *
 *     · 没开那道门时，它**根本不进候选**；
 *     · 开了门、模型也选了它，没有授权时**文件还在**；
 *     · 路径逃逸照旧被拒（它和读、写共用同一个 `safePath`）。
 *
 * @module JevLoop/act-local.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm, readdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { callTool, isToolName, type ToolRegistry } from '../src/act.ts'
import { LOCAL_TOOLS } from '../src/act-local.ts'
import { toolsFor } from '../src/frame.ts'
import { FRAME_SPECS } from '../src/decisions.ts'
import { compileFrame } from '../src/frame.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import { runAgent } from '../src/agent.ts'
import type { AgentCtx } from '../src/frame.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'

async function withTmp<T>(fn: (cwd: string) => Promise<T>): Promise<T> {
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-delete-'))
  try {
    return await fn(cwd)
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
}

// ═══════════════════════════════════════════════════════════
// ① 阶梯：哪几档有真东西可指
// ═══════════════════════════════════════════════════════════

test('★ 风险阶梯的最高档第一次有真东西可指', () => {
  assert.equal(LOCAL_TOOLS.delete_file.baseRisk, 3, 'delete_file 必须是 destructive（3）')
  assert.equal(
    LOCAL_TOOLS.write_file.baseRisk,
    1,
    'write_file 是可逆写入（1）—— 它不该因为旁边多了个删除就改档',
  )

  const rungs: Record<number, string[]> = {}
  for (const [name, tool] of Object.entries(LOCAL_TOOLS)) {
    const rung = (rungs[tool.baseRisk] ??= [])
    rung.push(name)
  }
  assert.deepEqual(rungs[0]?.sort(), ['done', 'list_dir', 'read_file'], '0 = 只读')
  assert.deepEqual(rungs[1], ['write_file'], '1 = 可逆写入')
  assert.deepEqual(rungs[3], ['delete_file'], '3 = 破坏性')
})

test('★ 已知缺口：第 2 档（irreversible）仍然是空的 —— 清单钉在这里', () => {
  /*
    阶梯是四档，而现在只有 0 / 1 / 3 有工具。第 2 档空着**是有意的现状**，
    不是漏写：能指向它的候选是 `move_file`（改名之后原路径就没了），
    而它的输入是**两行**（来源 + 目标），目标不在任何闭集里 ——
    那需要一条和 `write_file` 不同的生成路径，属于单独一刀。

    这条测试是**强制选择**：谁往注册表里加了 2 档的工具，它就会红，
    于是他必须回来更新这里（以及 DOCS 里那句「第 2 档还空着」）。
  */
  const irreversible = Object.entries(LOCAL_TOOLS)
    .filter(([, t]) => t.baseRisk === 2)
    .map(([n]) => n)
  assert.deepEqual(
    irreversible,
    [],
    '第 2 档有工具了 —— 请把这条测试和文档里的「还空着」一起更新',
  )
})

test('删除的目的是**不可撤销**的：描述里必须说出来，模型才有依据打分', () => {
  assert.match(LOCAL_TOOLS.delete_file.description, /不可撤销/, '描述要写明不可撤销')
})

// ═══════════════════════════════════════════════════════════
// ② 它真的会删 —— 以及沙箱照旧
// ═══════════════════════════════════════════════════════════

test('删掉一个文件，返回里点名删了谁', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'gone.txt'), 'bye', 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'delete_file', 'gone.txt', cwd)
    assert.match(out, /gone\.txt/, `返回要点名删了哪个文件，实际：${out}`)
    assert.equal(existsSync(join(cwd, 'gone.txt')), false, '文件应当真的没了')
  })
})

test('空目录可以删，非空目录**拒绝** —— 递归删是刻意的失控面', async () => {
  await withTmp(async (cwd) => {
    await mkdir(join(cwd, 'empty'))
    assert.match(await callTool(LOCAL_TOOLS, 'delete_file', 'empty', cwd), /已删除空目录/)

    await mkdir(join(cwd, 'full'))
    await writeFile(join(cwd, 'full', 'inside.txt'), 'x', 'utf8')
    const refused = await callTool(LOCAL_TOOLS, 'delete_file', 'full', cwd)
    assert.match(refused, /^错误：/, `非空目录必须被拒，实际：${refused}`)
    assert.deepEqual(await readdir(join(cwd, 'full')), ['inside.txt'], '里面的东西一个都不许少')
  })
})

test('★ 路径逃逸照旧被拒 —— 它和读、写共用同一个 safePath', async () => {
  await withTmp(async (cwd) => {
    const outside = join(cwd, '..', 'must-survive.txt')
    await writeFile(outside, 'safe', 'utf8')
    try {
      const out = await callTool(LOCAL_TOOLS, 'delete_file', '../must-survive.txt', cwd)
      assert.match(out, /路径逃出工作目录/, `工具目录外的路径必须被拒，实际：${out}`)
      assert.equal(existsSync(outside), true, '★ 目录外的文件必须还在')
    } finally {
      await rm(outside, { force: true })
    }
  })
})

// ═══════════════════════════════════════════════════════════
// ③ 候选门：没开门就**不存在**
// ═══════════════════════════════════════════════════════════

test('★ 没开 allowDelete 时，它根本不进候选 —— 现有调用方不会凭空多出一个删除工具', () => {
  const base: AgentCtx = { task: 't', cwd: '/w', files: ['a.txt'], canWrite: true }
  assert.equal('delete_file' in toolsFor(base), false, 'canWrite 不该把删除也放进来')
  assert.equal('delete_file' in toolsFor({ ...base, canDelete: false }), false)
  assert.equal('delete_file' in toolsFor({ ...base, canDelete: true }), true, '显式开了才进候选')
})

test('删过之后不再是候选（同 write_file：没有「还没删过」这种可判定目标）', () => {
  const ctx: AgentCtx = {
    task: 't',
    cwd: '/w',
    files: ['a.txt'],
    canDelete: true,
    history: [{ step: 1, tool: 'delete_file', input: 'a.txt', result: '已删除 a.txt' }],
  }
  assert.equal('delete_file' in toolsFor(ctx), false)
})

test('它的 criteria 是条件句，而且站在谨慎那一边', () => {
  const opts = toolsFor({ task: 't', cwd: '/w', files: ['a.txt'], canDelete: true })
  const criteria = opts.delete_file!
  assert.match(criteria, /requires|blocks progress/i, '要说清什么条件下才该选它')
  assert.match(criteria, /authorisation|授权/i, '要把「需要授权」写进判据 —— 问题 id 不会到达模型')
})

// ═══════════════════════════════════════════════════════════
// ④ 硬闸门：模型选了它，没有授权就**删不掉**
// ═══════════════════════════════════════════════════════════

test('★★ 端到端：模型选了 delete_file 而没人授权 —— 文件必须还在', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'precious.txt'), 'do not delete', 'utf8')
    await writeFile(join(cwd, 'other.txt'), 'x', 'utf8')

    // 一个「就是想把文件删掉」的判定后端：pick_tool 时永远选 delete_file
    const wantsToDelete = {
      name: 'wants-to-delete',
      decide: async (req: { questions: Record<string, { type: string; criteria?: unknown }> }) => {
        const answers: AnswerSet = {}
        for (const [id, q] of Object.entries(req.questions)) {
          if (q.type === 'noul') answers[id] = { type: 'noul', noul: 0.95 } as Answer
          else if (q.type === 'score') {
            // 破坏性 ⇒ 最高档。它是**模型**给的判断，不是工具自报的：
            // 这里刻意给 3，闸门必须据此拦下
            answers[id] = { type: 'score', score: 3, legend: {}, probabilities: {}, confidence: 0.95 } as Answer
          } else {
            const options = Object.keys((q as { criteria: Record<string, string> }).criteria)
            const choice = options.includes('delete_file') ? 'delete_file' : options[0]!
            /*
              ★ `probabilities` 必须填。第一版这里留了空对象，于是
                `pick_tool` 的 `top >= 0.6` 读到 0.000 → escalate → loop
                在**还没走到授权那一步**就停了 —— 文件当然还在，可那条断言
                是因为错误的原因通过的。下面那条轨迹断言把它抓了出来。
            */
            answers[id] = {
              type: 'choice',
              choice,
              probabilities: Object.fromEntries(
                options.map((o) => [o, o === choice ? 0.95 : 0.05 / Math.max(1, options.length - 1)]),
              ),
              confidence: 0.95,
            } as Answer
          }
        }
        return { answers, latencyMs: 0, provider: 'wants-to-delete' }
      },
    }

    const meter = new Meter()
    const decider = new Decider({ provider: wantsToDelete, meter })
    const traces: string[] = []
    await runAgent({
      task: '把这个目录清理干净',
      cwd,
      decider,
      // ★ 开门：允许删除进候选。授权钩子**故意不传** —— 默认拒绝
      allowDelete: true,
      provideWriteInput: () => 'precious.txt',
      generator: {
        name: 'noop',
        generate: async () => ({ text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
      },
      maxSteps: 4,
      onTrace: (l) => traces.push(l),
    })

    assert.equal(
      existsSync(join(cwd, 'precious.txt')),
      true,
      '★ 没有授权就不能删 —— 这是整个风险阶梯存在的意义',
    )
    assert.ok(
      traces.some((l) => /ask_human|授权|authoris/i.test(l)),
      `轨迹里应当留下「卡在授权」这一步，实际：${JSON.stringify(traces.slice(-6))}`,
    )
  })
})

test('★ 硬闸门确实由 base_risk 推出来：destructive 的基线进了 grade_risk 的帧', () => {
  const ctx: AgentCtx = { task: 't', cwd: '/w', lastTool: 'delete_file' }
  const f = compileFrame(FRAME_SPECS['loop.gradeRisk']!, ctx)
  assert.equal(f.state.base_risk, 3, 'base_risk 要如实报出破坏性这一档')
  // 而 `DECISION.md` 的 `score:risk >= 2 → ask_human` 就是在这一档上拦下来的
})

// ═══════════════════════════════════════════════════════════
// ⑤ 名字仍是封闭表
// ═══════════════════════════════════════════════════════════

test('新工具进了封闭表：isToolName 认得它，别的名字照旧不认', () => {
  assert.equal(isToolName(LOCAL_TOOLS, 'delete_file'), true)
  assert.equal(isToolName(LOCAL_TOOLS, 'rm_rf'), false)
  // 契约仍然是「只认这一张表」，不是「认任何一个字符串」
  assert.ok(Object.hasOwn(LOCAL_TOOLS as ToolRegistry, 'delete_file'))
})
