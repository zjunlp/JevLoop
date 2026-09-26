/**
 * JevLoop · L0 词汇 —— 两种**指纹**
 *
 * 零 import、零 IO 的纯函数，所以放在最底下：**谁都依赖得了它，它不依赖谁**。
 * 下沉的理由和 `http-error.ts` 一样是层规则 —— 两个不同层的消费方都要它：
 *
 *     `frame.ts`  (L3)  编完帧要算指纹
 *     `decide.ts` (L2)  发请求时要把「帧 + 问题 + 选项」算成一个串
 *
 * 而 §11 不许 L2 import L3。共用的东西必须下沉，不能就地复制一份 ——
 * 复制一份就是「同名不同义」的温床（§8.16）。
 *
 * ★★ **两个指纹回答两个不同的问题，这是这个文件存在的全部理由。**
 *
 *     frameDigest    「它**看到了**什么」   —— 只有帧
 *     requestDigest  「它**被问了**什么」   —— 帧 + 问题 + 选项
 *
 *   这个项目在这件事上骗过自己一次（§8.17）：拿 `frame_digest` 相同的两次
 *   判定当成了「同一个请求」，而 291 次里有 3 次答案不同 —— 因为 `choice` 的
 *   **选项不在帧里**，换掉候选集，帧指纹一动不动。把同一个请求原样发 12 次
 *   是 12 次相同；真正的机制是**判定贴在门限边上**，而帧的指纹看不见那个差别。
 *
 *   ⇒ 凡是报「两次跑的是不是同一个判定」，比的是 `requestDigest`。
 *
 * @module JevLoop/frame-digest
 */

import { createHash } from 'node:crypto'

/**
 * 指纹的十六进制长度。
 *
 * 16 是**跟着冻结的 Python 那份**（`experiments/core/frame.py`）定的：
 * 两边跑同一批输入要能逐字比对，长度不同就没法比。
 */
export const DIGEST_CHARS = 16

/** 把一个值压成稳定的串 —— 键序也是被哈希的内容，重排就是换了帧 */
function hashOf(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex').slice(0, DIGEST_CHARS)
}

/**
 * **帧**的指纹：回答「它看到了什么」。
 *
 * 节点名一起进哈希：同样的正文出自不同判定，不该得到同一个串。
 */
export function frameDigest(node: string, state: Record<string, unknown>): string {
  // 声明顺序进哈希 —— Object.entries 保序，而顺序本身是帧的一部分
  return hashOf([node, Object.entries(state)])
}

/**
 * **请求**的指纹：回答「它被问了什么」。
 *
 * `questions` 连**选项**一起进哈希，所以换掉候选集一定换指纹 ——
 * 那正是 `frameDigest` 看不见、而 §8.17 骗过我们一次的那一类。
 */
export function requestDigest(frame: string, questions: unknown): string {
  return hashOf([frame, questions])
}
