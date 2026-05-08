# s06-context-compact 个人解读

## 问题: 请分析脚本是否会compact LLM的输出?

**不会**（micro_compact），**会**（auto_compact）。具体分析：

### Layer 1: `micro_compact` — 不压缩 LLM 输出

它只扫描 `role == "user"` 的消息里 `type == "tool_result"` 的部分：

```python
if msg["role"] == "user" and isinstance(msg.get("content"), list):
    for part_idx, part in enumerate(msg["content"]):
        if isinstance(part, dict) and part.get("type") == "tool_result":
```

LLM 的输出是 `role == "assistant"` 的消息，**完全不会被碰**。

### Layer 2 & 3: `auto_compact` — 会，但是整体替换

它把整个 `messages` 列表（包括所有 assistant 消息）全部丢给 LLM 做摘要，然后用一条 summary 消息替换掉所有内容：

```python
return [
    {"role": "user", "content": f"[Conversation compressed. Transcript: {transcript_path}]\n\n{summary}"},
]
```

assistant 的输出被"蒸馏"进了摘要里，原始内容消失，但完整历史已提前存到 `.transcripts/` 磁盘文件里。

### 总结

| 层 | 压缩目标 | 是否压缩 LLM 输出 |
|---|---|---|
| micro_compact | 旧的 tool_result 内容 | 否 |
| auto_compact / manual compact | 整个对话历史 | 是（转为摘要） |

## 问题: micro_compact流程是怎么样的?

`micro_compact` 的流程如下：

**1. 收集所有 tool_result**

扫描整个 `messages` 列表，找出所有 `role == "user"` 且 `type == "tool_result"` 的片段，记录它们的位置：

```python
tool_results = [(msg_idx, part_idx, part), ...]
```

**2. 判断是否需要压缩**

如果 tool_result 总数 ≤ `KEEP_RECENT`（3），直接返回，不做任何操作。

**3. 建立 tool_id → tool_name 的映射**

遍历所有 `role == "assistant"` 的消息，把 `tool_use` block 的 `id` 和 `name` 记录进 `tool_name_map`：

```
{ "toolu_abc123": "bash", "toolu_def456": "read_file", ... }
```

**4. 压缩旧结果（保留最近 3 条）**

对 `tool_results[:-3]`（即"最老的那些"）逐一判断，满足以下**全部条件**才替换：
- content 是字符串 且长度 > 100（太短的不值得压缩）
- tool_name **不在** `PRESERVE_RESULT_TOOLS`（即不是 `read_file`）

满足条件则替换为：
```python
result["content"] = "[Previous: used bash]"
```

---

用图表示整个决策过程：

```
所有 tool_result 数量 ≤ 3?
        |
       YES → 直接返回（不做任何事）
        |
        NO
        |
        v
对每个"旧" tool_result（最近3条以外的）:
    content 是短字符串（≤100）? → 跳过
    tool_name 是 read_file?      → 跳过（保护文件内容）
    否则                          → 替换为占位符
```

**关键设计意图**：`read_file` 的结果被刻意保留，因为那是"参考资料"——压缩掉会强迫 agent 重新读文件，浪费 token。`bash`、`write_file` 等的结果则是"用完即抛"，可以安全压缩。

## 问题: 工具调用结果中, read_file长度不应该是大头吗? 去压缩bash, write_file结果是不是没起到效果

你的分析是对的，这里确实存在一个设计上的矛盾。理性分析如下：

### 实际 token 分布

| Tool | 典型输出大小 | 被 micro_compact？ |
|---|---|---|
| `read_file` | 大（几百~几千行文件内容） | **否**（被保护） |
| `bash` | 中等（grep/find/test 输出） | 是 |
| `write_file` | 极小（"Wrote 500 bytes"） | 是 |
| `edit_file` | 极小（"Edited xxx"） | 是 |

`read_file` 是 token 大头，却被刻意保护；`write_file` / `edit_file` 的结果本来就很短，几乎没什么可压缩的。

### micro_compact 实际效果评估

**有效的场景**：agent 频繁跑 `bash` 且输出很大时（比如 `grep -r`、`pytest` 输出、`find .`），micro_compact 确实能省不少 token。

**无效的场景**：agent 主要在读文件做分析，`read_file` 结果堆积——此时 micro_compact 几乎无用，token 依然飙升，很快触发 auto_compact。

### 设计的真实意图

micro_compact 的首要目标其实是**正确性**而非**效率**：

- 压缩掉 `read_file` 结果 → agent 下轮还要引用这段代码时就"忘了" → 会引入 bug 或强迫重读
- 压缩 `bash` 结果是安全的，因为命令执行完后结果就是"过去式"

所以它本质上是一个**低成本的安全阀**，不是真正的省 token 利器。真正的减压靠 **auto_compact（Layer 2）**——一旦超过 50k token 阈值就全量摘要。

### 如果要改进

如果想让 micro_compact 真正有效，合理的方向是：

```python
# 方案A: read_file 也压缩，但只截断保留前 N 行
result["content"] = result["content"][:500] + "\n[truncated]"

# 方案B: 对 read_file 按"最近访问"淘汰，而非永久保留
# 只保留最近被引用的文件内容
```

这样才能对最大的 token 来源下手。当前设计是在"不出错"和"省 token"之间选了前者。

## 问题: micro_compact中, 为什么要做那几个数据之间的映射, 目的是什么?

这是因为 Anthropic API 中，**工具调用** 和 **工具结果** 是分离在两条消息里的，靠 `id` 串联：

```
assistant 消息:
  [tool_use block]
    id: "toolu_abc123"
    name: "bash"          ← tool name 在这里
    input: {"command": "ls"}

user 消息:
  [tool_result block]
    tool_use_id: "toolu_abc123"   ← 只有 id，没有 name
    content: "file1.py\nfile2.py"
```

`tool_result` 本身**不携带 tool name**，只有一个 `tool_use_id`。

所以 `micro_compact` 要压缩旧结果时，需要知道"这条结果是哪个工具产生的"（以便判断是否是 `read_file` 需要跳过），就必须先建立这个反查表：

```python
tool_name_map = {
    "toolu_abc123": "bash",
    "toolu_def456": "read_file",
    ...
}
```

然后通过 `tool_result` 的 `tool_use_id` 字段去查：

```python
tool_id = result.get("tool_use_id", "")
tool_name = tool_name_map.get(tool_id, "unknown")
if tool_name in PRESERVE_RESULT_TOOLS:   # {"read_file"}
    continue   # 跳过，不压缩
```

**一句话总结**：这个映射是为了从 `tool_result`（只有 id）反查出工具名称，进而决定这条结果是否应该被压缩。没有这个映射，就无法区分 `read_file` 和 `bash` 的结果。

## 问题: 文档里面写了三层压缩, 在我看来layer 2和layer 3效果是一样的, 只是触发方式不同. 请分析下我说的是否正确

你说的完全正确。看代码可以确认：

**Layer 2 和 Layer 3 调用的是同一个函数 `auto_compact()`：**

```python
# Layer 2: 自动触发
if estimate_tokens(messages) > THRESHOLD:
    messages[:] = auto_compact(messages)   # ← 同一个函数

# Layer 3: 手动触发
if manual_compact:
    messages[:] = auto_compact(messages)   # ← 同一个函数
```

执行逻辑完全相同：
1. 保存 transcript 到磁盘
2. 让 LLM 做摘要
3. 用一条 summary 消息替换全部 messages

**唯一的区别只是触发条件：**

| | Layer 2 | Layer 3 |
|---|---|---|
| 触发方式 | token 估算超过 50000 自动触发 | agent 主动调用 `compact` 工具触发 |
| 触发时机 | 每次 LLM 调用前检查 | agent 自己判断"该压缩了" |
| 执行逻辑 | `auto_compact()` | `auto_compact()` |

所以文档把它们分成两层，本质上是在区分**触发策略**而非**压缩机制**。称为"两种触发方式的同一层"更准确。文档将其分开描述，更多是为了教学上的清晰度。

## 问题: 手动调用compact tool的时候, 是通过`/compact`触发的, 如何能确保LLM将其正确理解为compact tool调用呢?

实际上代码里**没有任何对 `/compact` 的特殊解析**，看 `__main__` 部分：

```python
query = input("\033[36ms06 >> \033[0m")
# ...
history.append({"role": "user", "content": query})
agent_loop(history)
```

用户输入的任何内容（包括 `/compact`）都直接作为普通用户消息传给 LLM，没有预处理。

### 那 LLM 怎么知道要调用 compact tool？

完全依赖 LLM 的**推理能力**：

1. LLM 看到可用工具列表里有 `compact`，描述是 "Trigger manual conversation compression"
2. LLM 看到用户消息是 `/compact`
3. LLM 自己推断出"这是一个 slash command，应该调用同名工具"

这是 LLM 从大量训练数据中习得的模式——slash command 在 CLI/聊天产品里普遍对应功能触发。

### 这个机制可靠吗？

**不完全可靠**，存在潜在问题：
- 用户说"请帮我压缩一下对话"，LLM 也可能调用 compact tool（这是好的）
- 但也可能用户说 `/compact`，LLM 却回复一段解释文字而不调用工具

更可靠的做法是在 `__main__` 里显式拦截：

```python
if query.strip() == "/compact":
    history[:] = auto_compact(history)
    continue
```

直接 bypass LLM，在 harness 层保证执行。当前代码依赖 LLM 行为属于**隐式约定**，不是硬保证。

## 问题: auto_compact我看会保留compact前的messages, 这个保存了之后, 有后续使用吗?

**没有**，保存的 transcript 在代码里没有任何后续读取逻辑。

```python
def auto_compact(messages: list) -> list:
    # 保存到磁盘
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(transcript_path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    print(f"[transcript saved: {transcript_path}]")
    # ... 做摘要，返回新 messages
```

整个代码库里没有任何地方读取 `.transcripts/` 目录下的文件。

### 那它存在的意义是什么？

纯粹是**人工兜底**，面向的是开发者而非程序本身：

1. **事后审计**：压缩是有损的，如果 agent 后来表现异常，可以回翻原始对话找原因
2. **调试**：查看 LLM 做了哪些工具调用、输出了什么
3. **心理安全感**：数据没有真正丢失，只是移出了活跃上下文

如果要让它真正有用，需要额外实现"从 transcript 恢复"的逻辑，比如：

```python
# 目前不存在的功能
if user_says("/restore"):
    latest = sorted(TRANSCRIPT_DIR.glob("*.jsonl"))[-1]
    history[:] = load_transcript(latest)
```

所以现在的 transcript 存储是**单向写入，只供人看**，不是程序自动恢复机制。

## 问题: micro_compact是否会影响LLM的缓存? 因为context变了

**会影响，且超过阈值后每轮都有一次局部 cache miss。** 修正后的完整分析：

### 阶段一：tool_result 总数 ≤ 3

micro_compact 直接返回，messages 不变，**完全不影响缓存**。

### 阶段二：tool_result 总数 > 3（稳态）

每轮必然有一条结果**首次被压缩**：

```
Turn 4: r3 首次变为 "[Previous: used bash]"  → cache miss（从 r3 位置往后失效）
Turn 5: r4 首次被压缩                         → cache miss
Turn 6: r5 首次被压缩                         → cache miss
...
```

也就是说，**超过阈值后每轮固定一次 cache miss**，不是偶发的。

### 已压缩结果的行为

一旦某条结果被压缩为占位符（≤100字符），后续轮次对它来说内容不再变化，该位置**重新命中缓存**。但它之后的新内容每轮仍在扩展，cache miss 的位置只是随着对话向后滚动。

### read_file 的特殊性

`read_file` 结果永远不被压缩，内容稳定，**持续命中缓存**——但代价是它一直占用 token，加速触发 auto_compact。

### 总结

| 情况 | 缓存影响 |
|---|---|
| 总数 ≤ 3 | 无影响 |
| 总数 > 3 | 每轮一次局部 cache miss（滚动向后） |
| auto_compact 触发 | 全量 cache miss，从头重建 |

## 问题: micro_compact这个只是局部的cache miss, 其实整体命中的缓存还是很多的, 可以这么理解吧?

基本正确，但要加一个前提条件。

### 为什么整体命中率高

Anthropic 的 cache 是**前缀匹配**的。micro_compact 每轮只修改倒数第 4 条 tool_result（`KEEP_RECENT=3`，压缩的是第 `n-3` 条）：

```
[r0✓ r1✓ r2✓ ... r(n-4)✓ | r(n-3) ← 本轮首次压缩 | r(n-2) r(n-1) r(n)]
 ←————— 全部命中缓存 —————→  cache miss 从这里开始
```

随着对话增长，稳定前缀越来越长，cache miss 的位置始终在"尾部附近"，**大头都能命中**。

### 前提条件

这个结论成立的前提是 `read_file` 结果没有大量堆积。如果 agent 读了很多文件，这些结果永远不被压缩，稳定前缀里夹杂着大量 `read_file` 内容，虽然缓存能命中，但 token 消耗居高不下，auto_compact 会很快被触发——届然整个 cache 清零，前面积累的命中率优势全部归零。

所以：**在 `bash` 为主的任务里，你的理解正确；在 `read_file` 密集的任务里，micro_compact 的缓存优势很快会被 auto_compact 截断。**