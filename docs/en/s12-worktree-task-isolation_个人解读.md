# s12-worktree-task-isolation 个人解读

## 分析: worktree task isolation原理

### 核心思想：控制平面与执行平面分离

```
控制平面 (.tasks/)          执行平面 (.worktrees/)
  任务状态 / 目标              目录隔离 / 执行上下文
  task_id 是纽带 ──────────────────────────────►
```

两个平面通过 `task_id` 双向绑定，各司其职：`TaskManager` 管"做什么"，`WorktreeManager` 管"在哪做"。

---

### 状态机

**Task 状态机**
```
pending ──bind_worktree()──► in_progress ──remove(complete_task=True)──► completed
```

**Worktree 状态机**
```
absent ──create()──► active ──keep()──► kept
                         └──remove()──► removed
```

关键设计：`bind_worktree()` 同时推进两个状态机：
```python
def bind_worktree(self, task_id, worktree, owner=""):
    task["worktree"] = worktree          # 执行平面写入控制平面
    if task["status"] == "pending":
        task["status"] = "in_progress"  # 自动推进任务状态
```

同理，`remove(complete_task=True)` 一次调用完成：删目录 → 更新任务为 `completed` → 解绑 → 发事件。

---

### 隔离机制

每个 worktree 是独立的 git branch + 独立目录：

```python
self._run_git(["worktree", "add", "-b", branch, str(path), base_ref])
# 等价于: git worktree add -b wt/auth-refactor .worktrees/auth-refactor HEAD
```

所有命令通过 `cwd=worktree_path` 锁定在隔离目录执行，物理上不共享工作区文件：
```python
subprocess.run(command, shell=True, cwd=path, ...)
```

名称校验防止路径注入：
```python
re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name)
```

---

### 可观测性：append-only 事件流

`EventBus` 写入 `.worktrees/events.jsonl`，每个生命周期节点都有 `before/after/failed` 三段式事件：

```
worktree.create.before → worktree.create.after
                       → worktree.create.failed

worktree.remove.before → task.completed (if complete_task)
                       → worktree.remove.after
```

这是崩溃恢复的基础——对话内存是易失的，文件状态是持久的：
- `.tasks/task_N.json` 持久化任务状态
- `.worktrees/index.json` 持久化 worktree 注册表
- `.worktrees/events.jsonl` 持久化生命周期日志

崩溃后从这三个文件即可完整重建状态，无需依赖会话历史。

---

### 设计权衡

| 关注点 | 方案 |
|---|---|
| 并行隔离 | 每个任务独占 git worktree 目录，互不干扰 |
| 状态一致性 | task/worktree 双向写入在同一进程内串行完成，无锁 |
| 安全性 | 命令黑名单 + path escape 校验 + `cwd` 限定 |
| 可恢复性 | 所有状态落盘，事件流记录操作顺序 |
| 收尾灵活性 | keep（保留目录）vs remove（清理目录）两种策略 |

## 分析: task是否必须和worktree绑定, 可以不绑定吗?

可以不绑定。

两者完全解耦，绑定是**可选**的。

**task 不绑定 worktree**：正常使用，`worktree` 字段为空字符串，任务独立存在于 .tasks 中。

**worktree 不绑定 task**：`task_id=None`，worktree 独立运行，不关联任何任务：
```python
WORKTREES.create("auth-refactor")          # 不传 task_id
WORKTREES.create("auth-refactor", task_id=1)  # 绑定
```

源码中所有涉及 `task_id` 的地方都有判空保护：
```python
if task_id is not None and not self.tasks.exists(task_id):
    raise ValueError(...)

if complete_task and wt.get("task_id") is not None:
    self.tasks.update(...)   # 只有绑定了才触发
```

**典型使用场景对比：**

| 场景 | task | worktree |
|---|---|---|
| 简单目标追踪 | ✓ | 不需要 |
| 临时实验分支 | 不需要 | ✓ |
| 并行任务隔离 | ✓ | ✓（绑定，推荐） |