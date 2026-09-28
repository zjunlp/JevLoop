/**
 * `jevloop/contract` 这个入口的**门禁**。
 *
 * ═══════════════════════════════════════════════════════════
 * 它要能**单独**成立 —— 不加载参考运行时
 * ═══════════════════════════════════════════════════════════
 *
 * 背景：包根（`index.ts`）转出了 `decisions.ts`，而它在**模块加载时**就把本仓库
 * 那份 `DECISION.md` 读进来、校验帧声明，不合格当场抛。所以外部 runtime 只要
 * `import { adapterProblems } from 'jevloop'`，就会被拖进整个参考运行时 ——
 * 还得**我们那份** `DECISION.md` 存在且合格，哪怕它想检查的是自己的契约。
 *
 * `src/contract.ts` 就是为这件事开的第二个入口。
 *
 * ★ 这个文件**只从 `../src/contract.ts` import** —— 这一条就是测试的一半：
 *   如果那个入口漏掉了什么、需要从别处再拿一个函数，这里立刻编译不过。
 *
 * ★ 另一半（「不许 import `decisions.ts` / `agent.ts` / `frame.ts`」）由层号
 *   机器保证：`scripts/check.ts` 把 `contract` 登记为 L3，而依赖只能指向编号
 *   更小的层，所以那三个文件 import 不进来，写了 `npm run check` 就红。
 *   在这里再抄一遍那条规则只会多一处会过期的东西。
 *
 * @module JevLoop/contract.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  adapterProblems,
  compilePolicy,
  compileQuestions,
  parseDecisionDoc,
  resolvePolicy,
  schemaProblems,
  CURRENT_SCHEMA,
  type AdapterCapabilities,
  type AnswerSet,
} from '../src/contract.ts'

const read = (name: string): string => readFileSync(new URL(name, import.meta.url), 'utf8')

const reference = parseDecisionDoc(read('../DECISION.md'))
const custom = parseDecisionDoc(read('../examples/custom-graph.DECISION.md'))

test('契约入口能独立读一份文件，并认得它的版本', () => {
  assert.deepEqual(schemaProblems(reference), [], '参考契约应当声明一个受支持的版本')
  assert.equal(reference.schema, CURRENT_SCHEMA)
})

test('★ 没写 schema 的文件会被这一层挡下 —— 其余三层一条都不响', () => {
  const bare = parseDecisionDoc('## foo\nkind: rule\nwhen: after-tool\n')
  assert.deepEqual(bare.problems, [], '其余解析层不该因此报错（这正是版本要单独一层的原因）')
  assert.ok(
    schemaProblems(bare).some((m) => m.includes('schema')),
    `应当报出缺版本，实际：${JSON.stringify(schemaProblems(bare))}`,
  )
})

test('★ 认不出的 schema 会被挡下，并带上行号', () => {
  const future = parseDecisionDoc('schema: decision-contract/v99\n\n## foo\nkind: rule\n')
  const problems = schemaProblems(future)
  assert.ok(problems.some((m) => m.includes('v99')), JSON.stringify(problems))
  assert.ok(problems.some((m) => m.startsWith('L1')), `应当带行号，实际：${JSON.stringify(problems)}`)
})

test('契约入口能把每个块编成问题与策略', () => {
  let blocks = 0
  for (const block of reference.blocks) {
    blocks++
    const questions = compileQuestions(block)
    if (block.kind === 'rule') {
      assert.equal(questions, undefined, `${block.id} 是 rule，不该有问题`)
      continue
    }
    assert.ok(questions && Object.keys(questions).length > 0, `${block.id} 应当编得出问题`)

    const policy = compilePolicy(block)
    assert.ok(policy?.ok, `${block.id} 的策略应当编得过：${policy?.problems.join('; ')}`)

    // 走一遍完整的一条链：问题 → 答案 → 动作。外部宿主干的就是这件事。
    const answers = Object.fromEntries(
      Object.entries(questions).map(([id, q]) => [
        id,
        q.type === 'noul'
          ? { type: 'noul' as const, noul: 0.9 }
          : q.type === 'score'
            ? { type: 'score' as const, score: 0, legend: {}, probabilities: {}, confidence: 0.9 }
            : { type: 'choice' as const, choice: Object.keys(q.criteria)[0]!, probabilities: {}, confidence: 0.9 },
      ]),
    ) as AnswerSet
    const outcome = resolvePolicy(policy.rules, answers)
    assert.equal(typeof outcome.action, 'string', `${block.id} 应当给出一个动作`)
  }
  assert.equal(blocks, 7, '参考契约有七个块')
})

test('契约入口能核对宿主能力：够用放行，缺一项就报出来', () => {
  const caps: AdapterCapabilities = {
    stateCells: ['task', 'earlier', 'already_done', 'files_known', 'already_read', 'last', 'tool', 'input', 'output', 'target', 'evidence', 'answer'],
    projections: ['earlierMaybe', 'describeDone', 'filesMaybe', 'readMaybe', 'lastOrNone', 'toolOrEmpty', 'lastResult', 'lastInput', 'toolOrUnknown', 'localToolRisk', 'resultMaybe', 'readCount', 'recentSteps', 'draftMaybe', 'writeEvidence'],
    dynamicProviders: ['toolsFor', 'unreadFiles'],
    positions: {
      'step-start': ['use_tool', 'answer'],
      'tool-choice': ['call'],
      'input-choice': ['use'],
      'before-call': ['auto', 'auto_audit', 'ask_human'],
      'after-tool': ['continue', 'stop', 'finish', 'keep_going'],
      'after-generate': ['deliver', 'revise'],
    },
    actions: ['answer', 'ask_human', 'auto', 'auto_audit', 'call', 'continue', 'deliver', 'escalate', 'finish', 'keep_going', 'revise', 'stop', 'use', 'use_tool'],
  }
  assert.deepEqual(adapterProblems(reference, caps), [])

  const thin = adapterProblems(reference, { ...caps, projections: [] })
  assert.ok(thin.length > 0, '一个投影都没注册就不该放行')
  assert.ok(thin.every((p) => p.block && p.message), '每条问题都要带上是哪个块')
})

test('两份契约都属于当前版本 —— fixture 不能落后于规范', () => {
  for (const [name, doc] of [['DECISION.md', reference], ['custom-graph.DECISION.md', custom]] as const) {
    assert.deepEqual(schemaProblems(doc), [], `${name} 的版本声明不合格`)
    assert.deepEqual(doc.problems, [], `${name} 不该有解析问题`)
  }
})
