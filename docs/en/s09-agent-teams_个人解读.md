# s09-agent-teams 个人解读

## 分析: agent teams的原理是什么?

## Agent Teams 原理

核心思想：**多个持久化 LLM 实例通过文件邮箱异步通信**。

### 1. 架构层次

```
Lead (主线程 REPL)
  ├── 负责接收用户输入
  ├── 调用 9 个工具（含 spawn/send/broadcast）
  └── 与 Teammate 通过 BUS 通信

Teammate-alice (独立线程)        Teammate-bob (独立线程)
  └── 自己的 agent loop            └── 自己的 agent loop
```

每个 Teammate 是**一个真正的 LLM 推理循环**，运行在独立线程中，不是简单的 shell 进程。

---

### 2. 与 s04 Subagent 的关键区别

| | Subagent (s04) | Teammate (s09) |
|---|---|---|
| 生命周期 | spawn → 执行 → 销毁 | spawn → idle ↔ working → shutdown |
| 状态 | 无 | `config.json` 持久化 |
| 通信 | 只返回 summary | 双向消息传递 |

---

### 3. 两个核心组件

**TeammateManager** — 管理 Teammate 生命周期：
- `spawn()` 在 `config.json` 注册成员，起一个 daemon thread 跑 `_teammate_loop()`
- `_teammate_loop()` 是真正的 agent loop：每轮迭代先 **drain inbox → 注入上下文 → LLM 推理 → 执行工具**，循环最多 50 次
- 结束后状态改为 `idle`（而非销毁）

**MessageBus** — append-only JSONL 文件邮箱：
- `send()` → 追加一行 JSON 到 `inbox/{name}.jsonl`
- `read_inbox()` → 读全部消息 **并清空文件**（drain 语义）
- `broadcast()` → 遍历所有成员逐个 send

---

### 4. 通信流程

```
alice.send("bob", "fix this bug")
  → 写入 .team/inbox/bob.jsonl

bob 的 agent loop 下一轮：
  read_inbox("bob")
  → 读出消息，append 到 messages 列表
  → LLM 看到消息，做出响应
  → 可再 send_message 回给 alice
```

关键设计：Teammate **不是被动轮询**，而是每次调用 LLM 前都先 drain 自己的 inbox，消息作为 `user` 角色注入对话历史。

---

### 5. 5种消息类型

| 类型 | 用途 |
|---|---|
| `message` | 普通消息 |
| `broadcast` | 广播给所有人 |
| `shutdown_request` | 请求优雅关闭（s10） |
| `shutdown_response` | 批准/拒绝关闭（s10） |
| `plan_approval_response` | 批准/拒绝计划（s10） |

后三种是为 s10（更复杂的协商协议）预留的扩展点。

---

**一句话总结**：每个 Teammate 是一个带状态的持久 LLM 线程，通过文件系统上的 append-only JSONL 邮箱异步通信，inbox drain 语义保证消息只被消费一次。

## 分析: 我运行了一遍脚本, 这是输出, 请帮忙分析下执行流程:

```bash
python3 agents/s09_agent_teams.py
s09 >> Spawn alice (coder) and bob (tester). Have alice send bob a message.
> spawn_teammate:
Spawned 'alice' (role: coder)
> spawn_teammate:
Spawned 'bob' (role: tester)
  [bob] read_inbox: []
> list_teammates:
Team: default
  alice (coder): working
  bob (tester): working
> read_inbox:
[]
  [alice] send_message: Sent message to bob
  [alice] read_inbox: []
> read_inbox:
[]
Here's a summary of what's been done:

- ✅ **alice** (coder) — spawned and working
- ✅ **bob** (tester) — spawned and working
- ✅ Alice was instructed to send a friendly greeting to bob via `send_message`, and bob was instructed to listen for it and reply.

Both teammates are running in their own threads, so alice should be sending bob a message right about now, and bob will reply. Since their direct messages are peer-to-peer (not routed through the lead's inbox), I won't see them unless they choose to CC me. Everything is in motion! 🚀
```

### 时间线（按输出顺序）

**1. Lead 接收用户输入，调用 LLM**
Lead 的 agent loop 启动，LLM 决定需要 spawn 两个 teammate。

**2. `spawn_teammate alice` → `spawn_teammate bob`**
- 两个线程几乎同时启动
- alice/bob 各自开始自己的 `_teammate_loop()`
- config.json 记录两人状态为 `working`

**3. 并发执行（线程交错）**

```
主线程 (Lead)              alice 线程              bob 线程
--------------             ----------              ---------
                                                   read_inbox("bob") → []
spawn 完成后继续...
list_teammates →           
  alice: working
  bob: working
read_inbox("lead") → []
                           send("bob","hello")
                           read_inbox("alice") → []
read_inbox("lead") → []
LLM 输出最终回复
```

注意 `[bob] read_inbox: []` 出现在 `list_teammates` **之前**，说明 bob 线程抢先跑了一轮，但此时 alice 还没发消息，所以收到空。

**4. alice 发消息时机太晚**
alice 的 `send_message to bob` 发生在 lead 已经 `read_inbox` 完之后。bob 的线程在收到消息之前可能已经结束了（无 tool_use 则 break）。

---

### 关键问题：消息丢失的风险

```python
# _teammate_loop 中
for _ in range(50):
    inbox = BUS.read_inbox(name)
    ...
    if response.stop_reason != "tool_use":
        break  # ← bob 可能在这里提前退出，然后 alice 才发消息
```

bob 的初始 prompt 是"listen for a message"，但如果 LLM 判断没有 tool 需要调用（`stop_reason != "tool_use"`），bob 线程就退出了，之后 alice 写入 `bob.jsonl` 的消息**永远不会被读取**。

---

### Lead 的行为解释

Lead 做了 3 次 `read_inbox("lead")`，都是空的——因为 alice/bob 的任务描述里没有要求他们回报给 lead，所以 peer-to-peer 消息不经过 lead inbox，最后 LLM 只能说"我看不到他们之间的消息"。

---

### 一句话总结

流程正确：spawn → 并发执行 → alice 发消息给 bob → lead 无法感知。但存在**竞态**：bob 可能在 alice 发消息前就 idle/退出，导致消息被丢弃，这是 s09 的设计局限，s10 会通过更完善的协商协议来解决。

## 分析: 上面的那次运行, alice为什么知道自己要给bob发消息?

因为是 **Lead LLM 把指令写进了 `spawn_teammate` 的 `prompt` 参数**。

追踪一下调用链：

**1. 用户输入**
```
Spawn alice (coder) and bob (tester). Have alice send bob a message.
```

**2. Lead LLM 理解意图，调用 `spawn_teammate`**

Lead LLM 不只是 spawn，它还要把"发消息给 bob"这个任务翻译成 alice 的初始 prompt。它实际调用的大概是：

```python
spawn_teammate(
    name="alice",
    role="coder",
    prompt="You are alice, a coder. Send a friendly greeting message to bob."  # ← 关键
)
```

**3. 这个 prompt 成为 alice 线程的第一条消息**

```python
def _teammate_loop(self, name, role, prompt):
    messages = [{"role": "user", "content": prompt}]  # ← Lead 写的 prompt
    ...
    response = client.messages.create(...)  # alice 的 LLM 看到这个 prompt，决定调用 send_message
```

---

**本质：Lead LLM 是"翻译器"**

用户说的话 → Lead LLM 推理 → 拆解成每个 teammate 的初始任务 → 写入各自的 `prompt` 参数 → 各自的 LLM 独立执行

alice 自己并不"知道"全局，它只是看到自己的初始 prompt 里有"send message to bob"这条指令，就调用了 `send_message` 工具。整个"意图传递"靠的是 Lead LLM 在 spawn 时精心构造的 prompt 字符串。

## 分析: team成员的idle状态是不是没有用起来?

是的，**s09 中 `idle` 基本只是个标签，没有真正"用起来"**。

看代码里 `idle` 实际出现的两个地方：

**1. 线程结束时写入**
```python
# _teammate_loop 末尾
if member and member["status"] != "shutdown":
    member["status"] = "idle"  # 线程死了，状态改成 idle
    self._save_config()
```

**2. 防止重复 spawn**
```python
# spawn() 中
if member["status"] not in ("idle", "shutdown"):
    return f"Error: '{name}' is currently {member['status']}"
```

所以 `idle` 的唯一实际作用是：**阻止对一个还在运行的 teammate 重复 spawn**。

---

### 没有实现的部分

文档说的生命周期是 `spawn → WORKING → IDLE → WORKING → ...`，但 s09 里：

- 没有**唤醒机制**：teammate 变 idle 后线程就死了，inbox 里来新消息也不会自动唤起
- 没有**任务队列**：lead 无法把新任务推给已 idle 的 teammate
- 没有**事件驱动**：idle 状态不会触发任何回调

`idle` 在 s09 里更像是"这个人名还保留在花名册里，下次可以再 spawn"，而不是真正的待命状态。

---

**真正的 idle ↔ working 循环**要靠一个持久存活的线程 + 内部轮询 inbox 才能实现，这需要在 `_teammate_loop` 里加类似：

```python
# 伪代码：真正的 idle 循环
while not shutdown:
    inbox = BUS.read_inbox(name)
    if inbox:
        member["status"] = "working"
        # 处理消息...
        member["status"] = "idle"
    else:
        time.sleep(1)  # 真正的待命
```

s09 没有这个，`idle` 只是为 s10+ 的扩展预留的语义占位符。