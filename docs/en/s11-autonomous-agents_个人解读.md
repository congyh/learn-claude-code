# s11-autonomous-agents 个人解读

## 分析: autonomous agents原理

### 1. 整体架构：Lead + Teammate 双层模型

```
用户 ──► Lead (主线程, agent_loop)
              │
              ├── spawn_teammate ──► Teammate-A (独立 thread, _loop)
              ├── spawn_teammate ──► Teammate-B (独立 thread, _loop)
              └── spawn_teammate ──► Teammate-C (独立 thread, _loop)
```

**Lead** 是一个普通的 agent loop（`agent_loop()`），运行在主线程，接受用户 prompt，通过 `spawn_teammate` 工具创建 teammates。  
**Teammate** 每个都在独立的 daemon thread 中运行（`threading.Thread(daemon=True)`），拥有自己的生命周期状态机。

---

### 2. Teammate 生命周期：WORK / IDLE 两相状态机

s11_autonomous_agents.py 中 `_loop()` 方法体现了这个两相结构：

```
spawn
  │
  ▼
WORK 阶段 ─── LLM 调用 tool_use ─► 执行工具 ─► 继续循环
  │
  │ stop_reason != tool_use  OR  调用了 idle 工具
  ▼
IDLE 阶段 ─── 每 5s 轮询一次，最多 60s
  │
  ├── inbox 有消息？ ──► 注入 messages ──► 回到 WORK
  ├── 任务看板有未认领任务？ ──► claim ──► 回到 WORK
  └── 超时 60s ──────────────────────────► SHUTDOWN
```

关键细节：IDLE 阶段不调用 LLM，纯粹是 Python 层的轮询，节省 token 消耗。

---

### 3. 自治的核心机制：任务看板 + 原子认领

任务以 JSON 文件存储在 `.tasks/task_N.json`，结构为：

```json
{ "id": 1, "subject": "...", "status": "pending", "owner": null, "blockedBy": null }
```

`scan_unclaimed_tasks()` 过滤条件：`status == "pending" AND owner == null AND blockedBy == null`

认领时用 **`_claim_lock`（threading.Lock）** 保证原子性，避免多个 teammate 并发抢同一个任务：

```python
with _claim_lock:
    task = json.loads(path.read_text())
    if task.get("owner"):          # 二次检查，防止 TOCTOU
        return "Error: already claimed"
    task["owner"] = owner
    task["status"] = "in_progress"
    path.write_text(json.dumps(task, indent=2))
```

这是一个**基于文件系统的轻量级分布式锁**，通过 Python 互斥锁 + 读-检查-写的原子序列实现。

---

### 4. 消息总线：JSONL 收件箱

`MessageBus` 用每个 teammate 的独立 JSONL 文件（`.team/inbox/{name}.jsonl`）作为消息队列：

- **send**: append 一行 JSON
- **read_inbox**: 读全部行后**清空文件**（drain 语义，每条消息只消费一次）
- **broadcast**: 向所有 teammate 逐个 send

WORK 阶段每轮 LLM 调用前都会 `BUS.read_inbox(name)`，将消息注入 `messages` 列表，让 LLM 感知到通信内容。

---

### 5. 身份重注入：解决 Context Compression 问题

当 `len(messages) <= 3` 时，说明上下文被外部压缩过（消息记录异常短），teammate 可能忘了自己是谁。此时在 messages 开头插入身份块：

```python
if len(messages) <= 3:
    messages.insert(0, {"role": "user",
        "content": f"<identity>You are '{name}', role: {role}, team: {team_name}...</identity>"})
    messages.insert(1, {"role": "assistant",
        "content": f"I am {name}. Continuing."})
```

这利用了 LLM 对 user/assistant 交替结构的顺从性——伪造一个"我已经知道自己是谁"的历史对话，让模型继续工作而不迷失。

---

### 6. 新增工具（相对 s10）

| 工具 | 归属 | 作用 |
|------|------|------|
| `idle` | Lead + Teammate | Teammate 主动声明无活干，触发进入 IDLE 阶段 |
| `claim_task` | Lead + Teammate | 从任务看板认领指定 ID 的任务 |

`idle` 工具是 WORK→IDLE 状态转换的**显式信号**，比等 `stop_reason != tool_use` 更早触发，让 teammate 可以在完成一个子任务后主动让出控制权。

---

### 7. 关键设计权衡

| 问题 | 设计选择 |
|------|---------|
| 并发任务认领冲突 | threading.Lock + 文件级二次检查 |
| IDLE 期间不浪费 token | Python 层轮询，不调用 LLM |
| 身份遗忘 | messages 长度启发式判断 + 前插身份块 |
| Teammate 自动退出 | 60s 超时后 status → shutdown，thread 自然结束 |
| 依赖任务顺序 | `blockedBy` 字段，scan 时跳过被阻塞任务 |

## 分析: 分析执行过程

```bash
Python3 agents/s11_autonomous_agents.py
s11 >> Create 3 simple tasks (easy to complete) on the board, then spawn alice and bob. Watch them auto-claim.
> bash:
/Users/congyihao/IdeaProjects/learn-claude-code
total 208
drwxr-xr-x@ 22 congyihao  staff    704 May 10 18:05 .
drwxr-xr-x  28 congyihao  staff    896 May 10 16:03 ..
-rw-r--r--@  1 congyihao  staff  
> list_teammates:
No teammates.
> bash:
total 24
drwxr-xr-x@  5 congyihao  staff  160 May 10 18:02 .
drwxr-xr-x@ 22 congyihao  staff  704 May 10 18:05 ..
-rw-r--r--@  1 congyihao  staff  241 May 10 18:02 task_1.json
-rw-r--r--@  1 congyihao
> bash:
total 0
drwxr-xr-x@  3 congyihao  staff   96 May 10 18:05 .
drwxr-xr-x@ 22 congyihao  staff  704 May 10 18:05 ..
drwxr-xr-x@  2 congyihao  staff   64 May 10 18:05 inbox
> bash:
(no output)
> write_file:
Wrote 228 bytes
> write_file:
Wrote 214 bytes
> write_file:
Wrote 222 bytes
> spawn_teammate:
Spawned 'alice' (role: developer)
> spawn_teammate:
Spawned 'bob' (role: developer)
> idle:
Lead does not idle.
  [bob] bash: (no output)
  [alice] bash: total 24
drwxr-xr-x@  5 congyihao  staff  160 May 10 18:06 .
drwxr-xr-x@ 22 congyihao  staff  704 May 10 18:05 ..
-rw-r-
  [bob] bash: total 24
drwxr-xr-x@  5 congyihao  staff  160 May 10 18:06 .
drwxr-xr-x@ 22 congyihao  staff  704 May 10 18:05 ..
-rw-r-
> bash:
=== .tasks/task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_package/greeting.py that returns 'Hello, World!'",
  "
> read_inbox:
[]
> list_teammates:
Team: default
  alice (developer): working
  bob (developer): working
  [bob] read_file: {
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_p
  [bob] read_file: {
  "id": 2,
  "subject": "Update requirements.txt with requests",
  "description": "Add the 'requests' library to requi
  [bob] read_file: {
  "id": 3,
  "subject": "Create a .gitkeep in .team/inbox",
  "description": "Ensure the .team/inbox directory is trac
  [alice] edit_file: Edited .tasks/task_1.json
> bash:
=== .tasks/task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_package/greeting.py that returns 'Hello, World!'",
  "
  [alice] bash: total 16
-rw-r--r--@  1 congyihao  staff   243 May  8 14:58 __init__.py
drwxr-xr-x@  4 congyihao  staff   128 May  8 14:
  [bob] edit_file: Error: Text not found in /Users/congyihao/IdeaProjects/learn-claude-code/.tasks/task_1.json
  [alice] write_file: Wrote 92 bytes
  [bob] bash: cat: illegal option -- A
usage: cat [-belnstuv] [file ...]
  [alice] bash: Hello, World!
> bash:
=== .tasks/task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_package/greeting.py that returns 'Hello, World!'",
  "
  [bob] bash: {
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_p
  [alice] edit_file: Edited .tasks/task_1.json
  [bob] edit_file: Edited /Users/congyihao/IdeaProjects/learn-claude-code/.tasks/task_2.json
  [alice] edit_file: Error: Text not found in .tasks/task_2.json
> bash:
=== .tasks/task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_package/greeting.py that returns 'Hello, World!'",
  "
  [bob] read_file: anthropic>=0.25.0
python-dotenv>=1.0.0
pyyaml>=6.0
  [alice] read_file: {
  "id": 2,
  "subject": "Update requirements.txt with requests",
  "description": "Add the 'requests' library to requi
  [bob] edit_file: Edited /Users/congyihao/IdeaProjects/learn-claude-code/requirements.txt
  [alice] read_file: {
  "id": 3,
  "subject": "Create a .gitkeep in .team/inbox",
  "description": "Ensure the .team/inbox directory is trac
> bash:
def hello_world():
    """Return the classic greeting string."""
    return "Hello, World!"
> bash:
anthropic>=0.25.0
python-dotenv>=1.0.0
pyyaml>=6.0
requests>=2.28.0
  [bob] edit_file: Edited /Users/congyihao/IdeaProjects/learn-claude-code/.tasks/task_2.json
  [alice] edit_file: Edited .tasks/task_3.json
  [alice] bash: (no output)
  [bob] edit_file: Error: Text not found in /Users/congyihao/IdeaProjects/learn-claude-code/.tasks/task_3.json
> bash:
=== .tasks/task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_package/greeting.py that returns 'Hello, World!'",
  "
  [alice] write_file: Wrote 0 bytes
  [bob] bash: {
  "id": 3,
  "subject": "Create a .gitkeep in .team/inbox",
  "description": "Ensure the .team/inbox directory is trac
  [alice] edit_file: Edited .tasks/task_3.json
  [alice] bash: === task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_worl
  [bob] bash: {
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_p
> bash:
=== .tasks/task_1.json ===
{
  "id": 1,
  "subject": "Add a hello world function",
  "description": "Create a simple hello_world() function in my_package/greeting.py that returns 'Hello, World!'",
  "
  [alice] idle: Entering idle phase. Will poll for new tasks.
  [bob] idle: Entering idle phase. Will poll for new tasks.
🎉 **All 3 tasks complete!** Here's the final board:

| # | Task | Owner | Status |
|---|------|-------|--------|
| 1 | Add `hello_world()` function | Alice | ✅ done |
| 2 | Update requirements.txt with requests | Bob | ✅ done |
| 3 | Create .gitkeep in .team/inbox | Alice | ✅ done |

**What they auto-accomplished:**
- **Alice** claimed #1 and #3 — wrote `my_package/greeting.py` and created `.team/inbox/.gitkeep`
- **Bob** claimed #2 — added `requests>=2.28.0` to `requirements.txt`

Both teammates found work independently, claimed what was free, and delivered without any hand-holding. Want me to shut them down, or keep them around for more tasks?
```

### 阶段一：Lead 初始化（主线程）

```
> bash: ls ./ → 探索工作目录
> list_teammates: No teammates → 确认当前无人
> bash: ls .tasks/ → 发现已有 task_1.json（上次残留）
> bash: ls .team/ → 确认 inbox 目录存在
> bash: (no output) → 清理旧 task 文件
> write_file × 3 → 写入 task_1/2/3.json
> spawn_teammate: alice
> spawn_teammate: bob
> idle: Lead does not idle → Lead 尝试进入 idle，但被拦截（Lead 不 idle）
```

**关键观察**：Lead 在 `write_file` 写完任务、`spawn_teammate` 之后就尝试调用 `idle`，说明 LLM 理解"自己的工作已经完成了"——创建任务 + 启动人手，剩下的交给 teammates 自治。

---

### 阶段二：Alice 和 Bob 并发启动（两个独立 thread）

```
[bob] bash: (no output)    ← Bob 先做了什么空操作（可能是检查环境）
[alice] bash: ls .tasks/   ← Alice 同时扫描任务看板
[bob] bash: ls .tasks/     ← Bob 也在扫描
```

两个 thread 几乎同时启动，都在 **WORK 阶段**扫描 .tasks 目录。这里出现了**竞争**。

---

### 阶段三：任务争抢（核心冲突现场）

```
[bob] read_file: task_1.json  ← Bob 读了所有三个 task
[bob] read_file: task_2.json
[bob] read_file: task_3.json
[alice] edit_file: Edited .tasks/task_1.json  ← Alice 抢先 claim 了 task_1
[bob] edit_file: Error: Text not found in .tasks/task_1.json  ← Bob 输了！
```

**Bob 的失败原因**：Bob 的策略是"先读再改"，但 Alice 已经抢先修改了 `task_1.json`（把 `"owner": null` 改成了 `"owner": "alice"`），导致 Bob 的 `edit_file` 找不到原文本。这正是 `_claim_lock` 保护的场景——但这里 LLM 是直接调 `edit_file` 工具修改文件的（**绕过了** `claim_task` 工具！），所以锁没生效，退化为"文件内容不匹配"作为隐式锁。

---

### 阶段四：各自分工

```
[alice] write_file: greeting.py (92 bytes)  ← 完成 task_1 实际工作
[alice] bash: Hello, World!                 ← 验证函数输出
[bob] edit_file: Edited task_2.json         ← Bob 转去 claim task_2
[bob] edit_file: Edited requirements.txt    ← Bob 完成 task_2
[alice] read_file: task_2.json              ← Alice 也去看 task_2
[alice] read_file: task_3.json              ← Alice 发现 task_3 还没人做
[alice] edit_file: Edited task_3.json       ← Alice claim task_3
[bob] edit_file: Error: Text not found in task_3.json  ← Bob 再次输
```

**同样的竞争模式重演**：Bob 慢了一步，task_3 也被 Alice 拿走。

---

### 阶段五：收尾

```
[alice] write_file: Wrote 0 bytes  ← 创建 .gitkeep（空文件）
[alice] idle: Entering idle phase  ← Alice 没活了，主动 idle
[bob] idle: Entering idle phase    ← Bob 也没活了
```

两者都进入 **IDLE 阶段**，开始每 5s 轮询，等待新任务。60s 后若无任务则自动 shutdown。

---

### 完整时序图

```
时间轴 ──────────────────────────────────────────────────►
 
Lead:   [ls][ls][ls][清理][write×3][spawn alice][spawn bob][idle]
                                        │           │
Alice:                               [启动][扫描][claim#1][做#1][验证][claim#3][做#3][idle]
                                                       │
Bob:                                 [启动][读#1#2#3][失败#1][claim#2][做#2][失败#3][idle]
```

---

### 值得注意的现象

| 现象 | 解释 |
|------|------|
| Bob 两次 `Error: Text not found` | LLM 直接用 `edit_file` 修改任务状态，而非调 `claim_task` 工具，没有走互斥锁，但文件内容不匹配起到了相同效果 |
| `cat: illegal option -- A` | Bob 在 macOS 上用了 Linux 专有的 `cat -A` 命令，LLM 的跨平台意识不足 |
| Alice 完成了 task_1 和 task_3 | Bob 因为"先读后写"策略更慢，Alice 的"直接 claim 再做"更快 |
| Lead 调用 `idle` 被拒 | 代码硬编码 `"Lead does not idle."`，Lead 的 `idle` 不触发轮询，这是 Lead 和 Teammate 角色的一个分叉 |

## 问题; 为什么会出现LLM直接调用edit_file, 跳过claim_task工具的情况? 有没有优化方案?

### 根本原因：工具描述歧义 + LLM 的泛化倾向

看 `_teammate_tools()` 中两个工具的描述：

```python
{"name": "edit_file",   "description": "Replace exact text in file."}
{"name": "claim_task",  "description": "Claim a task from the task board by ID."}
```

LLM 在推理时会这样想：

> "我要认领 task_1，我需要把 `task_1.json` 里的 `"owner": null` 改成 `"owner": "bob"`。我有 `edit_file` 可以直接做这件事，为什么要多调一个 `claim_task`？"

这是 LLM 的**能力过剩（capability overshoot）**——它拥有一个万能工具 `edit_file`，自然会用它走捷径，绕过语义更高层的专用工具。`claim_task` 的描述没有传达"**你必须用我，否则并发安全无法保证**"的紧迫性。

---

### 优化方案

#### 方案 A（最快）：强化工具描述，明确禁止绕过

```python
# 改前
{"name": "claim_task", "description": "Claim a task from the task board by ID."}
{"name": "edit_file",  "description": "Replace exact text in file."}

# 改后
{"name": "claim_task",
 "description": "REQUIRED: Claim a task before working on it. "
                "Use this instead of edit_file on task files. "
                "Handles concurrency safely — edit_file on .tasks/ is forbidden."}
{"name": "edit_file",
 "description": "Replace exact text in a file. "
                "Do NOT use on .tasks/ files — use claim_task instead."}
```

成本最低，但 LLM 不保证 100% 遵守——提示工程有概率失效。

---

#### 方案 B（最稳）：在 `_exec` 中拦截对 .tasks 的直接写操作

```python
def _exec(self, sender: str, tool_name: str, args: dict) -> str:
    # 拦截 edit_file / write_file 直接操作 .tasks/
    if tool_name in ("edit_file", "write_file"):
        path = args.get("path", "")
        if ".tasks/" in path or path.startswith(".tasks"):
            return ("Error: Direct writes to .tasks/ are forbidden. "
                    "Use claim_task to claim, then update_task to change status.")
    ...
```

这是**强制约束**，不依赖 LLM 的理解。无论 LLM 怎么推理，代码层面保证绕不过去。

---

#### 方案 C（最完整）：拆分 `claim_task` 为两步，并增加 `update_task`

当前 `claim_task` 做了两件事（`owner` + `status`），但 LLM 无法用它更新 `status: completed`，所以它不得不用 `edit_file` 收尾。这是另一个触发绕过的原因。

```python
# 增加 update_task 工具
{"name": "update_task",
 "description": "Update task status (in_progress/completed/failed). Only the owner can update.",
 "input_schema": {"type": "object",
   "properties": {
     "task_id": {"type": "integer"},
     "status": {"type": "string", "enum": ["in_progress", "completed", "failed"]},
     "result": {"type": "string"}
   },
   "required": ["task_id", "status"]}}
```

```python
def update_task(task_id: int, owner: str, status: str, result: str = "") -> str:
    with _claim_lock:
        path = TASKS_DIR / f"task_{task_id}.json"
        task = json.loads(path.read_text())
        if task.get("owner") != owner:
            return f"Error: Only the owner can update task {task_id}"
        task["status"] = status
        if result:
            task["result"] = result
        path.write_text(json.dumps(task, indent=2))
    return f"Task {task_id} updated to {status}"
```

这样 .tasks 的完整生命周期都有专用工具覆盖，LLM 没有理由再碰 `edit_file`。

---

### 三个方案对比

| 方案 | 实现成本 | 可靠性 | 副作用 |
|------|---------|--------|--------|
| A 强化描述 | 极低（改字符串） | 中（LLM 可能仍绕过） | 无 |
| B 代码拦截 | 低（加 5 行） | 高（强制执行） | LLM 会收到报错，需重试 |
| C 增加 update_task | 中（新工具+实现） | 最高（全覆盖） | 增加工具数量，稍微复杂 |

**推荐组合**：B + C——拦截是安全网，`update_task` 是正向引导，两者配合才能彻底解决问题。