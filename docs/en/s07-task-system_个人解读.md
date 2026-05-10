# s07-task-system 个人解读

## 问题: 告诉我当前task system设计的一些局限性

基于文档和代码，当前 task system 有以下几类主要局限：

---

**1. 并发安全问题（最严重）**

`_clear_dependency` 会循环读写所有 task 文件，没有任何文件锁。s09+ 引入多 agent 后，两个 agent 同时完成任务会产生 race condition，互相覆盖对方的写入。

同样，`_next_id` 是启动时算出的内存计数器——两个 agent 并发 `task_create` 会分配到相同 ID，后写的会覆盖前写的。

**2. 状态机不完整**

只有 `pending → in_progress → completed` 三态，没有 `failed` 状态。任务执行失败时只能留在 `in_progress`，无法区分"失败"和"运行中"，也无法阻止其依赖者被错误地解锁。

**3. 依赖图缺乏校验**

`update` 的 `add_blocked_by` 可以创建循环依赖（A blocked by B, B blocked by A），代码没有任何环检测，会导致所有相关任务永远无法变为 ready。

**4. 并行只是"可描述"，不能执行**

文档说 task graph 能识别"可并行的任务"，但 `agent_loop` 是单线程 REPL——根本没有调度器去实际并发执行 ready 状态的任务。图结构只是数据，执行层没有跟上。

**5. 缺失的元数据**

- 没有时间戳（创建/开始/完成时间），无法度量任务耗时或排查延迟
- `owner` 字段始终为空字符串，任何工具都不会写入它，多 agent 场景下无法做 ownership 约束
- 没有优先级字段，多个 ready 任务时 agent 只能随机选择

**6. 无法删除任务**

创建的任务只能 update，没有 delete 工具。测试或误创建的任务会永远留在 `.tasks/` 目录中，污染 `list_all` 的输出。

---

总结来看，s07 的设计对**单 agent、顺序执行**的场景足够用，但它声称是"s09+ 多 agent 协作的协调骨干"，而并发安全、失败处理、实际调度这几个核心问题都没有解决，是主要的结构性缺陷。

## 分析：s12（19-chapter-ver）修复了哪些缺陷，还有哪些问题

对比 s07 和 s12 的实现，s12 在**数据模型层**做了几项改进，但结构性缺陷基本未动。

**s12 已修复 / 改善的局限：**

| 局限（s07） | s12 的处理 |
|---|---|
| `owner` 无法写入 | `update()` 新增 `owner` 参数，`list_all` 也会输出，为多 agent ownership 分配打基础 |
| 无法删除任务 | 新增 `deleted` 状态（软删除），`list_all` 用 `[-]` 标记，不再污染 ready 列表 |
| 依赖图是单向的 | 引入 `blocks` 字段，`add_blocks` 时自动反向写入被阻塞任务的 `blockedBy`，双向图更完整 |

**s12 仍未解决的局限（原版结构性缺陷）：**

| 局限 | 状态 |
|---|---|
| **并发安全** | 未修。`_clear_dependency` 仍无文件锁；`_next_id` 仍是内存计数器，并发 create 会 ID 冲突 |
| **`failed` 状态缺失** | 未修。状态集是 `pending/in_progress/completed/deleted`，失败的任务仍无法区分于运行中 |
| **循环依赖检测** | 未修。`add_blocked_by` / `add_blocks` 均可创建环，没有任何 DAG 校验 |
| **并行只能描述，不能执行** | 未修。`agent_loop` 仍是单线程 REPL，task graph 的并行语义在执行层是空的 |
| **缺少时间戳 / 优先级** | 未修。无创建/完成时间，无 priority 字段 |
| **`list_all` 排序回退** | s12 移除了显式 `key=` 排序，改为字符串排序，`task_10` 会排在 `task_2` 前（s07 反而更正确） |

**核心判断：**

s12 的改动属于**数据模型增量**（双向边 + 软删除 + owner 可写），是为后续多 agent 章节（s15+）铺路的准备工作，而非对已知局限的系统性修复。真正的并发安全、失败处理和实际调度，在整个 learn-claude-code 系列中都没有在 task system 层面解决——这些问题被推迟到引入外部 broker 或专用编排框架时才处理，上一节列出的 Celery / Prefect / LangGraph 等方案仍是更完整的答案。

## 问题: 有没有优雅的task system开源方案

几个方向，由简到复杂：

---

**轻量级（最接近当前场景）**

- **[Celery](https://github.com/celery/celery)** — Python 任务队列，支持依赖链（chord/chain/group），持久化到 Redis/RabbitMQ，内置重试、失败状态、并发安全。对 agent 场景可以直接替换 `agent_loop` 的调度层。
- **[Dramatiq](https://github.com/Bogdanp/dramatiq)** — 比 Celery 更简洁的替代，API 设计更现代，同样支持 middleware 和 broker 持久化。

**DAG 编排（适合有依赖关系的 task graph）**

- **[Prefect](https://github.com/PrefectHQ/prefect)** — `@task` + `@flow` 装饰器，依赖关系通过返回值自动推断，有 UI dashboard，支持并发执行和失败重试。设计哲学和 s07 最接近，但解决了所有提到的局限。
- **[Dagster](https://github.com/dagster-io/dagster)** — 更强调数据血缘和 asset，适合数据 pipeline 场景，偏重型。

**专门为 AI agent 设计**

- **[LangGraph](https://github.com/langchain-ai/langgraph)** — 把 agent workflow 建模成状态机图，节点是 agent 调用，边是条件路由，原生支持循环、并行分支、持久化 checkpointing。解决的问题和 s07→s09 的演进路径几乎一致。
- **[Temporal](https://github.com/temporalio/temporal)** — 企业级工作流引擎，Go 写的，通过 event sourcing 实现持久化，天然解决并发安全和失败恢复，有 Python SDK。偏重但极其可靠。

---

**对应当前局限的方案选择：**

| 局限 | 推荐方案 |
|---|---|
| 并发安全 | Celery / Temporal |
| 失败状态 + 重试 | Celery / Prefect |
| 循环依赖检测 | Prefect / Dagster（DAG 校验内置）|
| 多 agent 调度 | LangGraph |
| 轻量可嵌入 | Dramatiq |

如果只是想改进 learn-claude-code 的教学代码而不引入外部依赖，**Prefect 的设计模式**值得直接借鉴——用装饰器声明任务和依赖，把调度和执行分离。