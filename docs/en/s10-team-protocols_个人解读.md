# s10-team-protocols 个人解读

## 分析: Team Protocols 原理解读

核心思想：**一个模式解决所有协商问题** — 请求方生成 `request_id`，响应方引用同一个 `request_id`，通过共享状态机追踪结果。

---

### 两种协议，同一结构

| | Shutdown Protocol | Plan Approval Protocol |
|---|---|---|
| **发起方** | Lead | Teammate |
| **响应方** | Teammate | Lead |
| **目的** | 优雅退出 | 高风险变更审批 |
| **状态机** | `pending → approved/rejected` | `pending → approved/rejected` |

---

### 状态机（FSM）

```
pending ──approve──> approved
       ──reject──> rejected
```

两个协议共用同一个 FSM，靠两个全局字典维护状态：

```python
shutdown_requests = {}   # {req_id: {"target": name, "status": "pending|approved|rejected"}}
plan_requests     = {}   # {req_id: {"from": name, "plan": "...", "status": "..."}}
```

---

### Shutdown Protocol 流程

**1. Lead 发起（生成 req_id，写入 shutdown_requests，发消息到 Teammate 收件箱）**

```python
def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "...", "shutdown_request", {"request_id": req_id})
```

**2. Teammate 响应（调用 `shutdown_response` 工具，更新共享字典，发回 Lead 收件箱）**

```python
if tool_name == "shutdown_response":
    shutdown_requests[req_id]["status"] = "approved" if approve else "rejected"
    BUS.send(sender, "lead", ..., "shutdown_response", {"request_id": req_id, "approve": approve})
    # approve=True 时 should_exit=True，线程退出
```

---

### Plan Approval Protocol 流程

**方向相反**：Teammate 先发，Lead 审批。

**1. Teammate 发起（生成 req_id，写入 plan_requests）**

```python
if tool_name == "plan_approval":
    req_id = str(uuid.uuid4())[:8]
    plan_requests[req_id] = {"from": sender, "plan": plan_text, "status": "pending"}
    BUS.send(sender, "lead", plan_text, "plan_approval_response", {"request_id": req_id})
```

**2. Lead 审批（引用同一 req_id，更新状态，发结果回 Teammate）**

```python
def handle_plan_review(request_id, approve, feedback=""):
    req = plan_requests[request_id]
    req["status"] = "approved" if approve else "rejected"
    BUS.send("lead", req["from"], feedback, "plan_approval_response", {"request_id": ..., "approve": approve})
```

---

### 消息总线（MessageBus）

```
.team/inbox/
  ├── lead.jsonl        ← Lead 的收件箱
  ├── alice.jsonl       ← alice 的收件箱
  └── bob.jsonl         ← bob 的收件箱
```

每条消息是一行 JSON（JSONL），`read_inbox` 读取后**立即清空**（drain），防止重复处理。消息类型通过 `VALID_MSG_TYPES` 白名单校验：

```python
VALID_MSG_TYPES = {"message", "broadcast", "shutdown_request", "shutdown_response", "plan_approval_response"}
```

---

### 关键设计点

1. **`request_id` 关联**：发送方生成，接收方回传，双方通过同一个 ID 对应请求和响应，无需共享内存（文件即总线）。

2. **线程安全**：所有对共享字典的读写都加 `_tracker_lock`，避免 Lead 主线程和 Teammate 子线程竞争。

3. **Teammate 的退出逻辑**：`should_exit` flag 在 `shutdown_response` approve 时置 True，下一轮循环开始前 `break`，保证当前任务写完再退出（优雅退出）。

4. **Lead 的 `shutdown_response` 工具语义不同**：Lead 端该工具实际是**查询状态**（`_check_shutdown_status`），而非发送响应——同名但语义不同，靠 `TOOL_HANDLERS` 映射区分。

## 分析: 执行过程分析

```bash
python3 agents/s10_team_protocols.py 
s10 >> Spawn bob with a risky refactoring task. Review and reject his plan.
> spawn_teammate:
Spawned 'bob' (role: backend engineer)
> read_inbox:
[]
  [bob] bash: (no output)
  [bob] bash: /Users/congyihao/IdeaProjects/learn-claude-code/.github/workflows/test.yml
/Users/congyihao/IdeaProjects/learn-claude-co
> read_inbox:
[]
  [bob] bash: /Users/congyihao/IdeaProjects/learn-claude-code/LICENSE
/Users/congyihao/IdeaProjects/learn-claude-code/requirements.txt
  [bob] read_file: name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-late
  [bob] read_file: name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  python-smoke:
    runs-on: ub
> bash:
done
> read_inbox:
[]
  [bob] bash: /Users/congyihao/IdeaProjects/learn-claude-code/web/scripts/extract-content.ts
/Users/congyihao/IdeaProjects/learn-claud
  [bob] bash: /Users/congyihao/IdeaProjects/learn-claude-code/LICENSE
/Users/congyihao/IdeaProjects/learn-claude-code/requirements.txt
> list_teammates:
Team: default
  bob (backend engineer): working
> bash:
done
> read_inbox:
[]
  [bob] read_file: {
  "name": "web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "extract": "tsx scripts/extract-content.t
  [bob] read_file: import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: t
  [bob] read_file: export const VERSION_ORDER = [
  "s01", "s02", "s03", "s04", "s05", "s06", "s07", "s08", "s09", "s10", "s11", "s12"
] as
> send_message:
Sent message to bob
> bash:
done
> read_inbox:
[]
> bash:
total 208
drwxr-xr-x@ 21 congyihao  staff    672 May 10 17:16 .
drwxr-xr-x  28 congyihao  staff    896 May 10 16:03 ..
-rw-r--r--@  1 congyihao  staff   2142 May  8 16:26 .env
-rw-r--r--@  1 congyihao
> bash:
total 8
drwxr-xr-x@  4 congyihao  staff  128 May 10 17:46 .
drwxr-xr-x@ 21 congyihao  staff  672 May 10 17:16 ..
-rw-r--r--@  1 congyihao  staff  141 May 10 17:46 config.json
drwxr-xr-x@  3 congyihao 
> bash:
total 8
drwxr-xr-x@ 3 congyihao  staff   96 May 10 17:47 .
drwxr-xr-x@ 4 congyihao  staff  128 May 10 17:46 ..
-rw-r--r--@ 1 congyihao  staff  180 May 10 17:47 bob.jsonl
> read_file:
{"type": "message", "from": "lead", "content": "Hey Bob, how's that refactoring plan coming along? I'm ready to review it whenever you've got it.", "timestamp": 1778406446.186643}
> read_file:
{
  "team_name": "default",
  "members": [
    {
      "name": "bob",
      "role": "backend engineer",
      "status": "working"
    }
  ]
}
> bash:
total 440
-rw-r--r--@  1 congyihao  staff    203 May  8 12:39 __init__.py
drwxr-xr-x@ 16 congyihao  staff    512 May  8 12:39 .
drwxr-xr-x@ 21 congyihao  staff    672 May 10 17:16 ..
-rw-r--r--@  1 co
> read_file:
#!/usr/bin/env python3
# Harness: protocols -- structured handshakes between models.
"""
s10_team_protocols.py - Team Protocols

Shutdown protocol and plan approval protocol, both using the same
reque
> bash:
total 8
drwxr-xr-x@ 3 congyihao  staff   96 May 10 17:47 .
drwxr-xr-x@ 4 congyihao  staff  128 May 10 17:46 ..
-rw-r--r--@ 1 congyihao  staff  180 May 10 17:47 bob.jsonl
---
No lead.jsonl yet
  [bob] plan_approval: Plan submitted (request_id=0b5c199d). Waiting for lead approval.
> bash:
{"type": "plan_approval_response", "from": "bob", "content": "## JWT-Based Stateless Authentication Refactoring Plan\n\n### Summary\nReplace the existing session-based authentication with a JWT-based 
  [bob] send_message: Sent message to lead
  [bob] read_inbox: []
> read_inbox:
[
  {
    "type": "message",
    "from": "bob",
    "content": "Hey! The plan's already been submitted for your review \u2014 it should be waiting in your queue (request_id: `0b5c199d`). \n\nTL;DR of 
> plan_approval:
Plan rejected for 'bob'
Done. Here's a summary of what happened:

---

### Bob's Task
I spawned **Bob** (backend engineer) and tasked him with a risky refactoring: replacing session-based auth with JWT-based stateless tokens.

### Bob's Plan (request_id: `0b5c199d`)
Bob investigated the codebase and discovered there **is no existing auth module** — it's a statically-exported Next.js docs site. His plan proposed:
- Dropping `output: "export"` to enable server-side API routes
- Dual-token JWT pattern (access + refresh tokens)
- JWKS key management with 30-day rotation
- Redis blocklist for token revocation
- 4-week implementation timeline
- 3 unresolved open questions

### My Rejection — 5 Reasons:
1. **Architecture mismatch** — not a refactoring, it's a platform rewrite
2. **No existing auth** — building greenfield auth for a docs site with no requirements
3. **Infrastructure bloat** — Redis, JWKS, blocklists for a zero-server project
4. **Unresolved open questions** — core architecture undecided at submission time
5. **Unrealistic timeline** — 4 weeks is overly optimistic given the unknowns

Bob has been told to go back to the drawing board.
```

### 阶段一：Lead 生成任务，Spawn Bob

```
> spawn_teammate: Spawned 'bob' (role: backend engineer)
```
Lead 调用 `spawn_teammate`，在新线程中启动 Bob 的 `_teammate_loop`，同时写入 `config.json`（status: working）。Bob 收到的初始 prompt 是 "risky refactoring task"。

---

### 阶段二：两条线程并发运行

**Bob 线程（独立探索代码库）：**
```
[bob] bash: ...test.yml, ...LICENSE
[bob] read_file: CI workflow, test workflow
[bob] bash: extract-content.ts
[bob] read_file: package.json, next.config.ts, VERSION_ORDER
```
Bob 在做 **codebase exploration**，先找 CI/测试文件了解项目结构，再看 web 目录的 Next.js 配置——这正是他发现"没有现有 auth 模块"的过程。

**Lead 线程（轮询 inbox，同时执行辅助动作）：**
```
> read_inbox: []   ← 多次轮询，Bob 还没有提交 plan
> bash: done       ← Lead 自己也在跑 bash（查看目录结构）
> list_teammates   ← 查看 bob 状态：working
> send_message: Sent message to bob  ← Lead 主动催促
```
Lead 发送的那条消息（"Hey Bob, how's that refactoring plan coming along?"）被写入 `bob.jsonl`，Bob 下一轮 `read_inbox` 会读到。

---

### 阶段三：Plan Approval Protocol 触发

```
[bob] plan_approval: Plan submitted (request_id=0b5c199d). Waiting for lead approval.
```
Bob 调用 `plan_approval` 工具：
1. 生成 `req_id = "0b5c199d"`
2. 写入全局 `plan_requests["0b5c199d"] = {"from": "bob", "plan": "...", "status": "pending"}`
3. 通过 MessageBus 将 plan 写入 `lead.jsonl`

```
> bash: {"type": "plan_approval_response", "from": "bob", ...}
```
这里 Lead 用 bash 直接读了 `bob.jsonl` 文件——**不是正常协议流程**，是 Lead 在 debug 查看文件内容。

---

### 阶段四：Lead 读到 Plan，执行审批

```
> read_inbox: [{"type": "message", "from": "bob", ...}]
```
Lead 的 `agent_loop` 在每轮开头调用 `BUS.read_inbox("lead")`，读到 Bob 提交的 plan（内容被包裹进 `<inbox>` 标签注入对话）。

```
> plan_approval: Plan rejected for 'bob'
```
Lead 调用 `plan_approval` 工具（`handle_plan_review`）：
1. 查找 `plan_requests["0b5c199d"]`
2. 将 status 改为 `"rejected"`
3. 通过 MessageBus 将 rejection 写入 `bob.jsonl`

Bob 下一轮 `read_inbox` 会读到拒绝结果，然后应当回到待命状态。

---

### 关键时序图

```
Lead Thread                          Bob Thread
─────────────────────────────────────────────────────
spawn_teammate ──────────────────> [启动 bob 线程]
read_inbox (空)                      bash/read_file (探索)
bash/list_teammates                  bash/read_file (探索)
send_message ────────────────────> [写入 bob.jsonl]
read_inbox (空)                      read_inbox (读到催促消息)
                                     plan_approval ──────────> [写入 lead.jsonl]
                                                               [plan_requests["0b5c199d"] = pending]
read_inbox (读到 plan) <────────────────────────────────────
plan_approval(reject) ──────────────────────────────────────> [写入 bob.jsonl]
                                                               [plan_requests["0b5c199d"] = rejected]
```

---

### 一个值得注意的细节

日志里出现了：
```
> bash: total 8
drwxr-xr-x@ 3 congyihao  staff   96 May 10 17:47 .
-rw-r--r--@ 1 congyihao  staff  180 May 10 17:47 bob.jsonl
---
No lead.jsonl yet
```

这说明 Lead 在 Bob 提交 plan **之前**就已经去检查 inbox 目录了（`lead.jsonl` 不存在），然后 Bob 才写入。这体现了两个线程真正的**异步并发**，Lead 不会阻塞等待 Bob 的 plan，而是靠轮询发现。