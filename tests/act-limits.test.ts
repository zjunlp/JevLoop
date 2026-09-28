/**
 * 工具层的资源限制（TODO §8 第二条）。
 *
 * ═══════════════════════════════════════════════════════════
 * 三条限制，三条都在**契约**里，不在某个实现里
 * ═══════════════════════════════════════════════════════════
 *
 * §8 记着「沙箱只覆盖路径逃逸，CPU / 内存 / 磁盘 / 墙钟都没有上限」。这里补的是
 * 工具层的三条：**输入上限**（写多少）、**超时**（等多久）、**输出上限**（吐回多少）。
 *
 * ★ 它们住在 `act.ts` 而不是 `act-local.ts`，理由和 `isToolName` 一样：换一个
 *   工具后端（沙箱、远程 FS、测试桩）时，这三条必须还在。
 *
 * ★ 这个文件里最重要的两条断言是**否定式**的：
 *
 *     · 输入超限时，文件**一个字节都没被写**（检查在 `run()` 之前）；
 *     · 会留下副作用的工具**不许声明超时**（JS 取消不掉，报超时就是撒谎）。
 *
 * @module JevLoop/act-limits.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { DEFAULT_MAX_OUTPUT_CHARS, callTool, type ToolRegistry } from '../src/act.ts'
import { LOCAL_TOOLS } from '../src/act-local.ts'

async function withTmp<T>(fn: (cwd: string) => Promise<T>): Promise<T> {
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-limits-'))
  try {
    return await fn(cwd)
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
}

// ═══════════════════════════════════════════════════════════
// ① 输入上限 —— 在产生副作用**之前**拒绝
// ═══════════════════════════════════════════════════════════

test('★★ 写的内容超过上限：拒绝，而且**一个字节都没落盘**', async () => {
  await withTmp(async (cwd) => {
    const limit = LOCAL_TOOLS.write_file.maxInputChars!
    // 路径 + 换行 + 超限内容
    const huge = 'big.txt\n' + 'x'.repeat(limit)
    const out = await callTool(LOCAL_TOOLS, 'write_file', huge, cwd)

    assert.match(out, /^错误：/, `超限必须被拒绝，实际：${out.slice(0, 80)}`)
    assert.match(out, /没有执行/, '要说清这一调根本没跑 —— 而不是「失败了」')
    assert.equal(
      existsSync(join(cwd, 'big.txt')),
      false,
      '★ 检查在 run() 之前 ⇒ 文件不该存在。写在盘上再看结果就晚了',
    )
  })
})

test('刚好等于上限放行，超一个字符就拒 —— 界是闭的，和别处一致', async () => {
  await withTmp(async (cwd) => {
    const limit = LOCAL_TOOLS.write_file.maxInputChars!
    const path = 'ok.txt\n'
    const exact = path + 'x'.repeat(limit - path.length)
    assert.equal(exact.length, limit, '构造要精确命中的那个长度')
    assert.match(await callTool(LOCAL_TOOLS, 'write_file', exact, cwd), /^已写入/)

    const over = path + 'x'.repeat(limit - path.length + 1)
    assert.match(await callTool(LOCAL_TOOLS, 'write_file', over, cwd), /^错误：/)
  })
})

test('没声明输入上限的工具不受影响 —— 它只收一个路径', async () => {
  await withTmp(async (cwd) => {
    await writeFile(join(cwd, 'a.txt'), 'hello', 'utf8')
    assert.equal('maxInputChars' in LOCAL_TOOLS.read_file, false, '没声明就是没有这一项，不是 undefined 的声明')
    assert.equal(await callTool(LOCAL_TOOLS, 'read_file', 'a.txt', cwd), 'hello')
  })
})

// ═══════════════════════════════════════════════════════════
// ② 超时 —— 是「不再等」，不是「取消」
// ═══════════════════════════════════════════════════════════

test('超时的工具会返回一句错误，而不是把 loop 挂住', async () => {
  const hang: ToolRegistry = {
    slow: {
      name: 'slow',
      description: '永不返回',
      baseRisk: 0,
      timeoutMs: 30,
      run: () => new Promise<string>(() => {}),
    },
  }
  const started = Date.now()
  const out = await callTool(hang, 'slow', '', '/nowhere')
  const took = Date.now() - started

  assert.match(out, /^错误：/, `应当是错误串，实际：${out}`)
  assert.match(out, /30ms/, '要说清等了多久')
  assert.match(out, /可能仍在后台进行/, '★ 不许声称「它没发生」—— JS 取消不掉')
  assert.ok(took < 2000, `不该真的等下去，实际 ${took}ms`)
})

test('没声明超时的工具**不做 race** —— 会留下副作用的工具必须是这一种', async () => {
  let finished = false
  const slowButSafe: ToolRegistry = {
    slow: {
      name: 'slow',
      description: '慢，但不会留下副作用',
      baseRisk: 0,
      run: async () => {
        await new Promise((r) => setTimeout(r, 40))
        finished = true
        return 'done'
      },
    },
  }
  // 契约层给了 1ms 的输出上限也不影响：超时是按工具声明的，不是全局的
  const out = await callTool(slowButSafe, 'slow', '', '/nowhere')
  assert.equal(out, 'done')
  assert.equal(finished, true, '没有声明 timeoutMs ⇒ 一直等到它真的完成')
})

test('★ 会动盘的工具都不许声明超时 —— 清单钉在这里', () => {
  /*
    这条不是「都对」的断言，是**强制选择**：谁给一个会留下副作用的工具加上
    `timeoutMs`，它就会红，于是他必须回来读 `Tool.timeoutMs` 那段说明，
    并在这里表态。

    理由：超时的语义是「我不再等了」。`write_file` / `delete_file` 报超时而
    其实执行成功了，loop 会基于一件没发生的事继续往下走 —— 那比不设超时更糟。
  */
  const mutating = ['write_file', 'delete_file']
  for (const name of mutating) {
    assert.equal(
      (LOCAL_TOOLS as Record<string, { timeoutMs?: number }>)[name]!.timeoutMs,
      undefined,
      `${name} 会留下副作用，不该声明 timeoutMs`,
    )
  }
  // 反过来：只读的那两个**应当**声明（迟到的结果丢掉就行）
  assert.ok(LOCAL_TOOLS.read_file.timeoutMs, 'read_file 是只读的，应当声明超时')
  assert.ok(LOCAL_TOOLS.list_dir.timeoutMs, 'list_dir 是只读的，应当声明超时')
})

// ═══════════════════════════════════════════════════════════
// ③ 输出上限 —— 截断要**标注**，不静默缩水
// ═══════════════════════════════════════════════════════════

test('★ 输出超限被截，而且说清截了多少', async () => {
  const big: ToolRegistry = {
    firehose: {
      name: 'firehose',
      description: '吐回一大堆',
      baseRisk: 0,
      run: async () => 'y'.repeat(500),
    },
  }
  const out = await callTool(big, 'firehose', '', '/nowhere', { maxOutputChars: 100 })
  assert.ok(out.startsWith('y'.repeat(100)), '保留前 100 个字符')
  assert.match(out, /\+400 chars 被工具层截断/, `要标注被截了多少，实际结尾：${out.slice(-40)}`)
})

test('不超限就一个字节都不动 —— 上限不该改变正常输出', async () => {
  const small: ToolRegistry = {
    echo: {
      name: 'echo',
      description: '原样返回',
      baseRisk: 0,
      run: async (input: string) => input,
    },
  }
  const text = 'exactly what came in'
  assert.equal(await callTool(small, 'echo', text, '/nowhere', { maxOutputChars: 100 }), text)
})

test('错误串也受输出上限约束 —— 一个失败的巨长输出同样能撑爆上下文', async () => {
  const loud: ToolRegistry = {
    boom: {
      name: 'boom',
      description: '抛一个很长的错误',
      baseRisk: 0,
      run: async () => {
        throw new Error('z'.repeat(400))
      },
    },
  }
  const out = await callTool(loud, 'boom', '', '/nowhere', { maxOutputChars: 80 })
  assert.match(out, /被工具层截断/, `错误也要截并标注，实际结尾：${out.slice(-40)}`)
})

test('★ 默认上限是契约常量，且宽于任何现有工具的自限', async () => {
  // 钉住它：改了默认值就会红，因为那会**静默**改变所有工具的返回长度
  assert.equal(DEFAULT_MAX_OUTPUT_CHARS, 8000)
  // `read_file` 自限 4000（另加一个标注），所以今天的默认值对它是零改动 ——
  // 这条断言保证「加了上限」没有顺手改掉现有工具的行为
  await withTmp(async (cwd) => {
    const body = 'a'.repeat(9000)
    await writeFile(join(cwd, 'big.txt'), body, 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'read_file', 'big.txt', cwd)
    assert.ok(out.length <= DEFAULT_MAX_OUTPUT_CHARS, 'read_file 的输出在默认上限之内')
    assert.match(out, /\+5000 chars/, '它自己的截断标注仍然是 read_file 那一层的（4000 起）')
    assert.ok(!out.includes('被工具层截断'), '★ 默认上限不该对 read_file 生效 —— 它自限更紧')
  })
})

test('契约层的上限对**任何**提供者都生效，不靠工具自觉', async () => {
  // 一个完全不设防的提供者：契约层照样把它按住
  const naive: ToolRegistry = {
    leaky: {
      name: 'leaky',
      description: '没有任何自限',
      baseRisk: 0,
      run: async () => 'q'.repeat(DEFAULT_MAX_OUTPUT_CHARS + 1234),
    },
  }
  const out = await callTool(naive, 'leaky', '', '/nowhere')
  assert.match(out, /\+1234 chars 被工具层截断/, '超出的 1234 字符要被标注出来')
})

test('截断后仍然是字符串，且可读 —— 不要吐回半个多字节字符之外的东西', async () => {
  await withTmp(async (cwd) => {
    const body = '中'.repeat(30)
    await writeFile(join(cwd, 'zh.txt'), body, 'utf8')
    const out = await callTool(LOCAL_TOOLS, 'read_file', 'zh.txt', cwd)
    assert.equal(await readFile(join(cwd, 'zh.txt'), 'utf8'), body, '读文件不该改动它')
    assert.ok(out.includes('中'), '正常内容原样返回')
  })
})
