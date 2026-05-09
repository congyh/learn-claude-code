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