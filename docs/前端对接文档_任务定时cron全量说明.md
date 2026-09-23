# 任务定时（cron / 固定间隔）全量说明 —— 前端对接文档

> 适用：任务中心「定时/周期任务」的时间配置。
> 目标：**用户只选时间，不写 cron**。前端用"下拉 + 日期/时间选择器"生成 cron，调校验接口回显"下次执行时间"。
> 本文所有语法与边界行为均与实现一致，并有回归测试锁定：
> `tests/test_cron_schedule.py`（9 组，含 19 项预置映射表逐条断言）。

---

## 0. 一句话结论

后端有**两套调度**，`schedule` 二选一：

| 调度方式 | 适用 | 字段 | 示例 |
| --- | --- | --- | --- |
| **cron 定时** | "每天 8 点""每周一 9 点""每月 1 号" | `schedule.cron` | `{"cron": "0 8 * * *", "timezone": "Asia/Shanghai"}` |
| **固定间隔** | "每 30 分钟""每 2 小时"（从当前时刻起算，不取整点） | `schedule.interval_seconds` | `{"interval_seconds": 1800}` |

任务类型必须是 `periodic` 或 `scheduled`，`schedule` 才会被调度器接管。

---

## 1. cron 表达式定义：**5 个字段**

```
┌───────────── 分钟 minute        0-59
│ ┌─────────── 小时 hour          0-23
│ │ ┌───────── 日   day-of-month  1-31
│ │ │ ┌─────── 月   month         1-12
│ │ │ │ ┌───── 星期 day-of-week   0-6（0=周日，7 也代表周日）
│ │ │ │ │
* * * * *
```

字段之间用**空格**分隔，**必须正好 5 个**；否则报错：

```json
{"success": false, "error": "cron 必须是 5 个字段（分 时 日 月 周），当前: '0 9 * *'"}
```

> 不支持秒级（6 字段）、不支持年份字段。

---

## 2. 完整语法表（实测行为）

| 写法 | 含义 | 示例 | 展开结果 |
| --- | --- | --- | --- |
| `*` | 该字段全部值 | `* * * * *` | 每分钟 |
| `?` | **同 `*`**（不是"不指定"，后端当全量处理） | `0 9 ? * 1` | 每周一 09:00 |
| `a` | 单个值 | `0 9 * * 1` | 分钟=0、小时=9、周一 |
| `a-b` | 范围（含两端） | `0 9 * * 1-5` | 周一到周五 |
| `*/n` | 从该字段最小值起，每 n 个 | `*/15 * * * *` | 0,15,30,45 分 |
| `a-b/n` | 范围内每 n 个 | `0-30/10 * * * *` | 0,10,20,30 分 |
| `a,b,c` | 列表（可混用上面所有写法） | `0 9 * * 1,3,5` | 周一/三/五 |
| `a-b/n,c` | 组合 | `0-10/2,30 * * * *` | 0,2,4,6,8,10,30 分 |

**三条必须知道的边界行为**（实现细节，前端应避免生成异常写法）：

1. **越界值取交集，不报错**：`50-70` 分 → 只取 `50-59`；`1-999` 分 → 只取 `1-59`。
2. **字段解析后为空 → 回落成"全部"**：`60 * * * *` 的分钟字段全部越界 → 等价 `* * * * *`（**每分钟**，不是报错）。
3. **无法解析的片段被忽略**：`1-abc` → 该字段全忽略 → 回落"全部"；`5/2` 的步长被忽略（等价 `5`）。

> 结论：**越界/错写不会被拒绝，而是静默变宽**。前端务必用第 5 节的预置项 + 第 7 节校验接口，不要放任用户手写。

---

## 3. 日 vs 星期：标准 cron 的"或"语义（最容易理解错）

| 日字段 | 星期字段 | 行为 |
| --- | --- | --- |
| `*` | `*` | 每天都触发 |
| `1`（每月1号） | `*` | 只按"日"（每月 1 号） |
| `*` | `1`（周一） | 只按"星期"（每周一） |
| **`1`** | **`1`** | **两者取"或"**：每月 1 号 **或** 每周一（标准 cron 行为） |

星期编号：`0=周日, 1=周一, 2=周二, 3=周三, 4=周四, 5=周五, 6=周六, 7=周日`。

---

## 4. 不支持清单（前端不要提供这些入口）

| 不支持 | 说明 |
| --- | --- |
| 6 字段 / 秒级 | 最小粒度是**分钟** |
| `L`（当月最后一天）、`W`（最近工作日）、`#`（第几个星期几） | 解析器只支持 `* ? 值 范围 步长 列表` |
| `@daily` / `@hourly` 等宏 | 请展开成 5 字段 |
| `TZ=` 前缀 | 用 `schedule.timezone` 字段 |
| 年份字段 | 无 |

"每月最后一天"可用 `0 9 28-31 * *` 近似（28/29/30/31 都触发，前端需提示会多触发），或后台按需扩展。

---

## 5. 预置映射表（建议前端直接做成下拉，用户不用碰 cron）

同一张表在 `tests/test_cron_schedule.py::PRESETS` 里逐条断言，可放心使用。

| 展示名 | 生成 cron | 说明/用到的语法 |
| --- | --- | --- |
| 每分钟 | `* * * * *` | `*` |
| 每 5 分钟 | `*/5 * * * *` | `*/n` |
| 每 15 分钟 | `*/15 * * * *` | `*/n` |
| 每 30 分钟 | `0,30 * * * *` | 列表 |
| 每小时整点 | `0 * * * *` | 列表/固定分 |
| 每 2 小时 | `0 */2 * * *` | `*/n`（从 0 点对齐） |
| 每天 08:00 | `0 8 * * *` | 基础 |
| 每天 08:00 和 20:00 | `0 8,20 * * *` | 列表 |
| 工作日 09:00 | `0 9 * * 1-5` | 范围 |
| 每周一 09:00 | `0 9 * * 1` | 星期单值 |
| 周一/三/五 09:00 | `0 9 * * 1,3,5` | 星期列表 |
| 周末 10:00 | `0 10 * * 0,6` | 星期列表（0=周日） |
| 每周日 10:00 | `0 10 * * 7` | 7 也是周日 |
| 每月 1 日 09:00 | `0 9 1 * *` | 日单值 |
| 每月 1 日和 15 日 09:00 | `0 9 1,15 * *` | 日列表 |
| 每季度首日 09:00 | `0 9 1 1,4,7,10 *` | 月列表 |
| 每年 1 月 1 日 09:00 | `0 9 1 1 *` | 月+日 |
| 每 2 天 09:00 | `0 9 */2 * *` | 日 `*/n`（1,3,5…日） |
| 白天(8-18 点)每 30 分钟 | `*/30 8-18 * * *` | 时范围 + 分步长 |

### 时间选择器 → cron 生成公式

```js
// 每天 HH:mm
`${m} ${H} * * *`
// 每周（星期多选 dow[]，0=周日）HH:mm
`${m} ${H} * * ${dow.join(",")}`
// 每月（日期多选 day[]）HH:mm
`${m} ${H} ${day.join(",")} * *`
// 每 N 分钟
`*/${N} * * * *`
// 每 N 小时（N 整除 24，从 0 点对齐）
`0 */${N} * * *`
// 每月最后一个工作日等复杂规则 → 不支持，请引导用户改用固定间隔或拆分任务
```

---

## 6. 固定间隔模式（interval）

```json
{"interval_seconds": 1800, "timezone": "Asia/Shanghai"}
```

| 规则 | 说明 |
| --- | --- |
| 取值范围 | 必须 `> 0`（秒）；非法返回 `interval_seconds 必须大于 0` |
| 起算点 | **从注册（确认任务）那一刻**开始算：下次 = 现在 + 间隔，**不取整点** |
| 精度 | 调度器 1 秒 tick → 实际误差约 ±1s；建议 ≥60s |
| 与 cron 区别 | `interval_seconds: 3600` 从 10:07 起 → 11:07、12:07；`0 * * * *` → 11:00、12:00 |

前端建议用"每 N 分钟/小时"下拉 → 换算成 `N*60` / `N*3600`。

---

## 7. 校验与预览接口（前端必接）

### `GET /api/v2/tasks/schedule/preview`

校验时间规则并返回未来若干次执行时间。**前端不用自己实现 cron 解析**。

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `cron` | 二选一 | 5 字段表达式 |
| `interval_seconds` | 二选一 | 固定间隔（秒） |
| `timezone` | 否 | 默认 `Asia/Shanghai` |
| `count` | 否 | 1~20，默认 5；非数字/0/负数按默认 5；>20 按 20 |

```bash
curl 'http://<IP>:6789/api/v2/tasks/schedule/preview?cron=0%209%20*%20*%201&count=3'
```

```json
{
  "success": true,
  "data": {
    "ok": true,
    "kind": "cron",
    "timezone": "Asia/Shanghai",
    "error": "",
    "warning": "",
    "next_runs": [
      "2026-09-28T09:00:00+08:00",
      "2026-10-05T09:00:00+08:00",
      "2026-10-12T09:00:00+08:00"
    ]
  },
  "ok": true, "kind": "cron", "next_runs": ["..."]
}
```

非法规则（HTTP 仍 200，看 `data.ok`）：

```json
{
  "success": true,
  "data": {
    "ok": false, "kind": "cron", "timezone": "Asia/Shanghai",
    "error": "该时间规则在未来一年内不会触发（cron 无法在未来一年内匹配: '0 0 31 2 *'）",
    "warning": "", "next_runs": []
  }
}
```

**前端交互建议**：用户每次改动时间控件 → 防抖 300ms 调本接口 → 合法就显示"下次执行：2026-09-28 09:00"，不合法就把 `error` 红字提示，禁用"保存"。

### 错误文案（可直接展示给用户）

| 触发 | `error` |
| --- | --- |
| 字段数不对 | `cron 必须是 5 个字段（分 时 日 月 周），当前: '...'` |
| 规则永不触发（如 2/31、2/29 超出一年窗口） | `该时间规则在未来一年内不会触发（cron 无法在未来一年内匹配: '...'）` |
| 两者都没传 | `schedule 需含 cron（定时）或 interval_seconds（固定间隔）之一` |
| 间隔非法 | `interval_seconds 必须大于 0` / `interval_seconds 必须是整数秒，当前: '...'` |
| 时区名不识别（非致命） | `warning`: `时区 'XXX' 无法识别，将按本机本地时间执行` |

---

## 8. 任务接口契约（时间相关）

### 8.1 创建任务（带定时）

`POST /api/v2/tasks`

```json
{
  "topic": "每日巡检",
  "task_type": "periodic",
  "description": "每天 8 点巡检一遍",
  "agent_group_config": {"members": [{"agent_id": "kunming", "role": "worker"}]},
  "execution_mode": "manual",
  "require_confirmation": true,
  "schedule": {"cron": "0 8 * * *", "timezone": "Asia/Shanghai"}
}
```

响应（除原有字段外，新增`schedule` / `schedule_preview`，前端可直接展示下次执行）：

```json
{
  "success": true,
  "data": {
    "task_id": "task_xxx",
    "status": "draft",
    "schedule": {"cron": "0 8 * * *", "timezone": "Asia/Shanghai"},
    "schedule_preview": {"ok": true, "kind": "cron", "next_runs": ["2026-09-23T08:00:00+08:00", "..."]},
    "approval_url": "/api/v2/tasks/task_xxx/approve"
  }
}
```

**非法 cron → 直接失败，不会创建任务**：

```json
{"success": false, "error": "schedule 非法: cron 必须是 5 个字段（分 时 日 月 周），当前: '0 8 * *'"}
```

> `require_confirmation: true`（默认）时任务是 `draft`，**必须在确认后才真正排期**。

### 8.2 确认任务（可在此刻让用户改时间）

`POST /api/v2/tasks/{task_id}/approve`

```json
{
  "approved": true,
  "approved_by": "admin",
  "modified_config": {
    "schedule": {"cron": "0 9 * * 1-5", "timezone": "Asia/Shanghai"}
  }
}
```

响应：

```json
{
  "success": true,
  "data": {
    "task_id": "task_xxx",
    "status": "pending",
    "message": "任务已确认",
    "schedule_status": {
      "is_scheduled": true,
      "registered": true,
      "next_run": "2026-09-23T09:00:00+08:00",
      "run_count": 0,
      "last_error": "",
      "error": ""
    }
  }
}
```

- `modified_config.schedule` 非法 → `success:false` + `schedule 非法: ...`，**任务仍是 draft**（不会出现"确认了却没排期"）
- 若确认后未排期（例如周期任务压根没给时间规则），`message` 会明确写出来：

```json
{"message": "任务已确认，但未排期：调度配置缺失或非法：schedule 需含 cron（定时）或 interval_seconds（固定间隔）之一"}
```

### 8.3 暂停 / 恢复

```bash
POST /api/v2/tasks/{task_id}/pause     # 暂停：清空下次执行时间，不补跑
POST /api/v2/tasks/{task_id}/resume    # 恢复：按当前时间重新计算 next_run
```

```json
{"success": true, "data": {"task_id": "task_xxx", "status": "pending", "next_run": "2026-09-23T09:00:00+08:00"}}
```

### 8.4 转化任务类型（顺带设置时间）

`POST /api/v2/tasks/{task_id}/convert`，`body: {"target_type": "periodic", "schedule": {...}}`，
响应含 `schedule` 与 `schedule_status`（老任务置为 `converted`）。

### 8.5 查询排期

| 接口 | 用途 |
| --- | --- |
| `GET /api/tasks/scheduled` | 全部定时作业：`task_id / kind(cron\|interval) / cron / interval_seconds / timezone / enabled / last_run / next_run / run_count / last_error / name` |
| `GET /api/v2/tasks/{task_id}` | 任务详情（含 `schedule`） |
| `GET /api/tasks/stats` | `scheduled` 段统计：`job_count / enabled_count / cron_count / interval_count / total_runs / running` |

**权限**：`GET` 类为 read 权限；`POST/DELETE` 类为 write 权限。

---

## 9. 前端实现建议（推荐 UI）

```
重复方式： [不重复 ▾]   ← 选"不重复"= 不传 schedule（普通任务）
          ├ 按分钟 / 每小时   → 数字输入 N → cron 或 interval_seconds
          ├ 每天              → 时间选择器 HH:mm        → `${m} ${H} * * *`
          ├ 每周              → 星期多选 + HH:mm        → `${m} ${H} * * 1,3,5`
          ├ 每月              → 日期多选(1-31) + HH:mm  → `${m} ${H} 1,15 * *`
          ├ 自定义间隔        → 每 N 分钟/小时          → interval_seconds
          └ 高级(cron)        → 文本框（带语法提示 + 实时校验）

时区：     [Asia/Shanghai ▾]（默认，不必让用户改）
预览：     ⏱ 下次执行：2026-09-28 09:00（来自 preview 接口）
```

要点：

1. **永远显示"下次执行时间"**（用 preview 接口），用户看到具体时间才会放心；`draft` 阶段提示"确认后生效"。
2. 选择 **29/30/31 日** 时提示"该规则在 2 月可能不触发"；选 **2 月 29 日** 时提示"仅闰年触发，可能无法排期"。
3. 用 `interval_seconds` 表达"每 N 分钟/小时"，用 cron 表达"某时刻"，别混用（`*/30 * * * *` 是"每小时的第 0/30 分"，不是"从现在起每 30 分钟"）。
4. 保存前先调 preview，`data.ok=false` 直接拦截并展示 `error`。

---

## 10. 边界与运行语义（前端文案可引用）

| 场景 | 行为 |
| --- | --- |
| 时区 | `schedule.timezone` 默认 `Asia/Shanghai`；无法识别时按本机本地时间并给 warning |
| 调度精度 | 最小分钟；interval 由 1 秒 tick 驱动（±1s） |
| 服务重启 | 作业持久化在 `data/tasks/scheduled_jobs.json`，重启自动恢复（含 next_run） |
| 错过的触发点 | 恢复后**立即补跑一次**（`now >= next_run` 即触发），随后按规则计算下一次；暂停期间不补跑 |
| 暂停/恢复 | 暂停清空 `next_run`；恢复按"当前时间"重算（不追溯） |
| 删除任务 | 联动注销调度作业，无需手工清理 |
| 执行失败 | 记入 `last_error` / `run_count`（`GET /api/tasks/scheduled` 可见），不中断调度循环 |
| 单任务重复触发保护 | 同一 task_id 只保留一个作业（重新注册=覆盖） |

---

## 11. 自测（前端联调可直接用）

```bash
GW=http://127.0.0.1:6789

# 1) 预览：工作日 9 点
curl "$GW/api/v2/tasks/schedule/preview?cron=0%209%20*%20*%201-5&count=3"

# 2) 预览：每 30 分钟（固定间隔）
curl "$GW/api/v2/tasks/schedule/preview?interval_seconds=1800&count=3"

# 3) 非法：字段数不足
curl "$GW/api/v2/tasks/schedule/preview?cron=0%209%20*%20*"

# 4) 非法：永不触发（2 月 31 日）
curl "$GW/api/v2/tasks/schedule/preview?cron=0%200%2031%202%20*"

# 5) 创建 + 确认 + 查排期
curl -X POST "$GW/api/v2/tasks" -H 'Content-Type: application/json' -H 'X-User-Id: admin' -d '{
  "topic":"每日巡检","task_type":"periodic","execution_mode":"manual",
  "agent_group_config":{"members":[{"agent_id":"kunming","role":"worker"}]},
  "schedule":{"cron":"0 8 * * *"}}'
curl -X POST "$GW/api/v2/tasks/<task_id>/approve" -H 'Content-Type: application/json' -H 'X-User-Id: admin' -d '{"approved":true}'
curl "$GW/api/tasks/scheduled"
```
