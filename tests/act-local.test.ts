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
import { readFileSync, existsSync } from 'node:fs'
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

test('★ 风险阶梯的四档现在都有真东西可指', () => {
  assert.equal(LOCAL_TOOLS.delete_file.baseRisk, 3, 'delete_file 必须是 destructive（3）')
  assert.equal(
    LOCAL_TOOLS.write_file.baseRisk,
    1,
    'write_file 是可逆写入（1）—— 它不该因为旁边多了个删除就改档',
  )
  assert.equal(
    LOCAL_TOOLS.move_file.baseRisk,
    2,
    '★ move_file 必须是 irreversible（2）：原路径没了，但一个字节都没丢',
  )

  const rungs: Record<number, string[]> = {}
  for (const [name, tool] of Object.entries(LOCAL_TOOLS)) {
    const rung = (rungs[tool.baseRisk] ??= [])
    rung.push(name)
  }
  assert.deepEqual(rungs[0]?.sort(), ['done', 'list_dir', 'read_file'], '0 = 只读')
  assert.deepEqual(rungs[1], ['write_file'], '1 = 可逆写入')
  assert.deepEqual(rungs[2], ['move_file'], '★ 2 = irreversible —— 这一档原来是空的')
  assert.deepEqual(rungs[3], ['delete_file'], '3 = 破坏性')
})

test('★ 补上第 2 档之后**没有空档**：0/1/2/3 每一档都至少有一个工具', () => {
  /*
    这条是替换掉原来那条「已知缺口：第 2 档仍然是空的」的。

    ★ 原来那条测试是**强制选择**：谁往注册表里加了 2 档的工具它就会红，于是他
      必须回来更新它和文档。现在它红了、也按约定被换成了这条 —— 缺口补上之后，
      真正该被钉住的是「没有空档」，而且将来**任何一档变空**都要报出来。
  */
  const rungs = new Set(Object.values(LOCAL_TOOLS).map((t) => t.baseRisk))
  for (const rung of [0, 1, 2, 3]) {
    assert.ok(rungs.has(rung), `风险阶梯第 ${rung} 档不该是空的`)
  }
})

test('删除与移动的目的都是**不可逆**的：描述里必须说出来，模型才有依据打分', () => {
  assert.match(LOCAL_TOOLS.delete_file.description, /不可撤销/, '删除的描述要写明不可撤销')
  assert.match(LOCAL_TOOLS.move_file.description, /不可逆/, '★ 移动的描述要写明不可逆')
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

test('★★ move_file：移过去、原名没了，返回里点名从哪到哪', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'old.txt'), 'payload', 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'move_file', 'old.txt\nnew.txt', cwd)
    assert.match(out, /old\.txt/, `返回要点名来源，实际：${out}`)
    assert.match(out, /new\.txt/, `返回要点名目标，实际：${out}`)
    assert.equal(existsSync(join(cwd, 'old.txt')), false, '★ 原路径必须没了 —— 这就是 irreversible')
    assert.equal(readFileSync(join(cwd, 'new.txt'), 'utf8'), 'payload', '★ 内容一个字节都不许变')
  })
})

test('★★ 移动**拒绝覆盖**已存在的目标 —— 这一条就是 2 档与 3 档的分界', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'a.txt'), 'from', 'utf8')
    await writeFile(join(cwd, 'b.txt'), 'must survive', 'utf8')
    const refused = await callTool(LOCAL_TOOLS, 'move_file', 'a.txt\nb.txt', cwd)
    assert.match(refused, /^错误：/, `覆盖必须被拒，实际：${refused}`)
    assert.match(refused, /已存在/, '要说清是因为目标已存在')
    // ★ 两边都要还在：拒绝必须发生在**移动之前**
    assert.equal(readFileSync(join(cwd, 'a.txt'), 'utf8'), 'from', '来源不许动')
    assert.equal(readFileSync(join(cwd, 'b.txt'), 'utf8'), 'must survive', '★ 目标那份必须完好')
  })
})

test('★ 来源不存在 ⇒ 拒绝，而且不去动目标那边', async () => {
  await withTmp(async (cwd) => {
    const out = await callTool(LOCAL_TOOLS, 'move_file', 'nope.txt\nx.txt', cwd)
    assert.match(out, /^错误：/, `来源不存在必须被拒，实际：${out}`)
    assert.equal(existsSync(join(cwd, 'x.txt')), false, '什么都不该被创建')
  })
})

test('★ 来源与目标相同 ⇒ 拒绝，不谎报「已移动」', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'same.txt'), 'x', 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'move_file', 'same.txt\nsame.txt', cwd)
    assert.match(out, /^错误：/, `原地移动应当被拒，实际：${out}`)
    assert.equal(existsSync(join(cwd, 'same.txt')), true)
  })
})

test('★ 只有一行输入 ⇒ 拒绝（它不是「重命名成空名」）', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'one.txt'), 'x', 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'move_file', 'one.txt', cwd)
    assert.match(out, /^错误：/, `缺目标行必须被拒，实际：${out}`)
    assert.equal(existsSync(join(cwd, 'one.txt')), true, '文件必须还在')
  })
})

test('★ move_file **不创建**父目录 —— 失败的操作不该在盘上留下东西', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'f.txt'), 'x', 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'move_file', 'f.txt\nsub/f.txt', cwd)
    assert.match(out, /^错误：/, `目标目录不存在时应当失败，实际：${out}`)
    assert.equal(existsSync(join(cwd, 'sub')), false, '★ 不许顺手建出目录')
    assert.equal(readFileSync(join(cwd, 'f.txt'), 'utf8'), 'x', '来源必须还在')
  })
})

test('★ move_file 的**两个**路径都过 safePath —— 逃逸的两边都要挡住', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'inside.txt'), 'x', 'utf8')
    const escaped = await callTool(LOCAL_TOOLS, 'move_file', 'inside.txt\n../out.txt', cwd)
    assert.match(escaped, /路径逃出工作目录/, `目标逃逸必须被拒，实际：${escaped}`)
    assert.equal(existsSync(join(cwd, 'inside.txt')), true, '被拒之后来源必须还在')

    const escapedSrc = await callTool(LOCAL_TOOLS, 'move_file', '../out.txt\ninside2.txt', cwd)
    assert.match(escapedSrc, /路径逃出工作目录/, `来源逃逸必须被拒，实际：${escapedSrc}`)
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

test('★★ move_file 要**两道**门：只开一道时它不存在，两边都不许被放宽', () => {
  const base: AgentCtx = { task: 't', cwd: '/w', files: ['a.txt'] }
  assert.equal('move_file' in toolsFor(base), false, '一道门都没开 ⇒ 不存在')
  assert.equal(
    'move_file' in toolsFor({ ...base, canWrite: true }),
    false,
    '★ 只给 canWrite 不够 —— 移动会让**来源路径消失**，那一半是删除性质的',
  )
  assert.equal(
    'move_file' in toolsFor({ ...base, canDelete: true }),
    false,
    '★ 只给 canDelete 也不够 —— 目标位置会被**创建**，那一半是写入性质的',
  )
  assert.equal(
    'move_file' in toolsFor({ ...base, canWrite: true, canDelete: true }),
    true,
    '两道都给才进候选',
  )
})

test('★ move_file 的 criteria 也是条件句，而且写明需要授权', () => {
  const opts = toolsFor({ task: 't', cwd: '/w', files: ['a.txt'], canWrite: true, canDelete: true })
  const criteria = opts.move_file!
  assert.match(criteria, /different path|original path/i, '要说清什么条件下才该选它')
  assert.match(criteria, /authorisation|授权/i, '要把「需要授权」写进判据 —— 问题 id 不会到达模型')
})

test('移动过之后不再是候选（同 write_file / delete_file）', () => {
  const ctx: AgentCtx = {
    task: 't',
    cwd: '/w',
    files: ['a.txt'],
    canWrite: true,
    canDelete: true,
    history: [{ step: 1, tool: 'move_file', input: 'a.txt\nb.txt', result: '已移动 a.txt → b.txt' }],
  }
  assert.equal('move_file' in toolsFor(ctx), false)
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
      decide: async (req: {
        state: { base_risk?: number }
        questions: Record<string, { type: string; criteria?: unknown }>
      }) => {
        const answers: AnswerSet = {}
        for (const [id, q] of Object.entries(req.questions)) {
          /*
            ★ `needs_auth` 刻意给**低**分。第一版这里对所有 noul 都给 0.95，于是
              `prob:needs_auth >= 0.5 → ask_human` 那条规则先命中了 —— 测试通过，
              但它证明的是「needs_auth 能拦」，**不是**「风险档能拦」。
              把它压低之后，能拦住这次调用的就只剩下 `score:risk >= 2` 那一条，
              这条测试才真的在测风险阶梯。
          */
          if (id === 'needs_auth') answers[id] = { type: 'noul', noul: 0.1 } as Answer
          else if (q.type === 'noul') answers[id] = { type: 'noul', noul: 0.95 } as Answer
          else if (q.type === 'score') {
            // 风险分**读帧里的 `base_risk`**，不是写死一个数 —— 写死的话，
            // 把工具的档位改掉这条测试也照样通过（它就不再依赖阶梯了）
            answers[id] = {
              type: 'score',
              score: req.state.base_risk ?? 0,
              legend: {},
              probabilities: {},
              confidence: 0.95,
            } as Answer
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

test('★★ 端到端：模型选了 move_file 而没人授权 —— 文件必须**还在原位**', async () => {
  /*
    ★ 这条是第 2 档存在的意义本身：`score:risk >= 2 → ask_human` 那道硬闸门
      原来只有 3 档（delete_file）踩得到，而 2 档一直是空的。现在它有了真东西，
      所以要证明的正是「没人授权 ⇒ 移不动」—— 而不是「工具能移动文件」。

    ★ 判定后端**想移**：pick_tool 永远选 move_file，风险打 2。没有 onAskHuman，
      所以授权那一步应当是 deny，于是来源必须还在原位、目标不许被创建。
  */
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'stay.txt'), 'must not move', 'utf8')
    await writeFile(join(cwd, 'other.txt'), 'x', 'utf8')

    const wantsToMove = {
      name: 'wants-to-move',
      decide: async (req: {
        state: { base_risk?: number }
        questions: Record<string, { type: string; criteria?: unknown }>
      }) => {
        const answers: AnswerSet = {}
        for (const [id, q] of Object.entries(req.questions)) {
          // ★ 同 delete 那条：`needs_auth` 压低，让**风险档**成为唯一能拦住它的规则
          if (id === 'needs_auth') answers[id] = { type: 'noul', noul: 0.1 } as Answer
          else if (q.type === 'noul') answers[id] = { type: 'noul', noul: 0.95 } as Answer
          else if (q.type === 'score') {
            // 风险分读帧里的 `base_risk` —— 这样把档位改错，这条测试会红
            answers[id] = {
              type: 'score',
              score: req.state.base_risk ?? 0,
              legend: {},
              probabilities: {},
              confidence: 0.95,
            } as Answer
          } else {
            const options = Object.keys((q as { criteria: Record<string, string> }).criteria)
            const choice = options.includes('move_file') ? 'move_file' : options[0]!
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
        return { answers, latencyMs: 0, provider: 'wants-to-move' }
      },
    }

    const meter = new Meter()
    const decider = new Decider({ provider: wantsToMove, meter })
    const traces: string[] = []
    await runAgent({
      task: '把这个文件挪个地方',
      cwd,
      decider,
      // 两道门都开：它才可能进候选。授权钩子**故意不传** —— 默认拒绝
      allowDelete: true,
      provideWriteInput: () => 'stay.txt\nmoved.txt',
      generator: {
        name: 'noop',
        generate: async () => ({ text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
      },
      maxSteps: 4,
      onTrace: (l) => traces.push(l),
    })

    assert.equal(existsSync(join(cwd, 'stay.txt')), true, '★ 没有授权就移不动 —— 这是第 2 档存在的理由')
    assert.equal(
      readFileSync(join(cwd, 'stay.txt'), 'utf8'),
      'must not move',
      '内容也不许动',
    )
    assert.equal(existsSync(join(cwd, 'moved.txt')), false, '★ 目标不许被创建')
    assert.ok(
      traces.some((l) => /ask_human|授权|authoris/i.test(l)),
      `轨迹里应当留下「卡在授权」这一步，实际：${JSON.stringify(traces.slice(-6))}`,
    )
  })
})

test('★ 硬闸门确实由 base_risk 推出来：irreversible 的基线也进了 grade_risk 的帧', () => {
  const ctx: AgentCtx = { task: 't', cwd: '/w', lastTool: 'move_file' }
  const f = compileFrame(FRAME_SPECS['loop.gradeRisk']!, ctx)
  assert.equal(f.state.base_risk, 2, '★ 第 2 档要如实报出来 —— 它原来是一档没人走过的梯级')
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
