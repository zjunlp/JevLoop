/**
 * `JEVOS_JEV_URL` —— 「把判定请求指到别的端点」这件事到底做不做得到。
 *
 * ═══════════════════════════════════════════════════════════
 * 这条测试防的是一个**静默失效的配置**
 * ═══════════════════════════════════════════════════════════
 *
 * `.env` 与 `.env.example` 都写着 `JEVOS_JEV_URL`，`.env` 里也设了值。
 * 但 2026-09-26 实测：**全仓零个消费方** —— 把它设成本地地址会被静默忽略，
 * 请求照样发去 `https://api.typesafe.ai`。
 *
 * ★ 为什么这条不能只靠「读代码看出来」：那正是它躲了很久的原因 ——
 *   配置的文件在、变量名在、值也在，**看起来完全正常**。
 *   而它挡住的是一件真事：判定侧的墙钟几乎全是往返（实测 418ms/次 × 10 次），
 *   换成本地端点是把那笔账归零的唯一手段。
 *
 * ★ 所以这里起一个**真的 HTTP 服务器**，把变量指过去，看请求到不到 ——
 *   而不是断言某个私有字段。把那一行 `?? process.env.JEVOS_JEV_URL` 去掉，
 *   这条会红（§8.15 的判据）。
 *
 * @module JevLoop/jev-url.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer, type Server } from 'node:http'

/** 起一个只会记下「被打到了哪个路径」的假端点 */
async function fakeEndpoint(): Promise<{ url: string; hits: string[]; close: () => Promise<void> }> {
  const hits: string[] = []
  const server: Server = createServer((req, res) => {
    hits.push(req.url ?? '')
    res.writeHead(200, { 'content-type': 'application/json' })
    // 形状给足以免解析炸掉；内容不重要 —— 这里量的是**请求去了哪**
    res.end(JSON.stringify({ answers: {}, provider: 'fake' }))
  })
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r))
  const port = (server.address() as { port: number }).port
  return {
    url: `http://127.0.0.1:${port}`,
    hits,
    close: () => new Promise<void>((r) => server.close(() => r())),
  }
}

test('★ JEVOS_JEV_URL 真的生效 —— 判定请求打到它指的端点，不是官方默认', async () => {
  const fake = await fakeEndpoint()
  const prevUrl = process.env.JEVOS_JEV_URL
  const prevKey = process.env.TYPESAFE_API_KEY

  process.env.JEVOS_JEV_URL = fake.url
  process.env.TYPESAFE_API_KEY = 'test-key-not-used'
  try {
    const { resolveProvider } = await import('../src/backends.ts')
    const provider = resolveProvider({})

    // 不发判定也行 —— 下面断言的是**它去了哪**。
    // 端点会正常回一个空答案集，所以这一调用应当成功（或至少不该因为连不上而崩）。
    await provider.decide({ state: {}, questions: {} }).catch(() => undefined)

    assert.ok(
      fake.hits.includes('/v1/systemone'),
      `★ 请求必须打到 JEVOS_JEV_URL 指的端点（${fake.url}/v1/systemone），实际打到：${JSON.stringify(fake.hits)}`,
    )
  } finally {
    if (prevUrl === undefined) delete process.env.JEVOS_JEV_URL
    else process.env.JEVOS_JEV_URL = prevUrl
    if (prevKey === undefined) delete process.env.TYPESAFE_API_KEY
    else process.env.TYPESAFE_API_KEY = prevKey
    await fake.close()
  }
})

test('显式参数优先于环境变量（`choice.jevUrl` 仍然说了算）', async () => {
  const viaEnv = await fakeEndpoint()
  const viaArg = await fakeEndpoint()
  const prevUrl = process.env.JEVOS_JEV_URL
  const prevKey = process.env.TYPESAFE_API_KEY

  process.env.JEVOS_JEV_URL = viaEnv.url
  process.env.TYPESAFE_API_KEY = 'test-key-not-used'
  try {
    const { resolveProvider } = await import('../src/backends.ts')
    const provider = resolveProvider({ jevUrl: viaArg.url })
    await provider.decide({ state: {}, questions: {} }).catch(() => undefined)

    assert.ok(viaArg.hits.includes('/v1/systemone'), '显式给的那个必须赢')
    assert.deepEqual(viaEnv.hits, [], '环境变量在显式参数面前不该被用到')
  } finally {
    if (prevUrl === undefined) delete process.env.JEVOS_JEV_URL
    else process.env.JEVOS_JEV_URL = prevUrl
    if (prevKey === undefined) delete process.env.TYPESAFE_API_KEY
    else process.env.TYPESAFE_API_KEY = prevKey
    await viaEnv.close()
    await viaArg.close()
  }
})
