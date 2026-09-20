# 昆明配网数据 API 调用技能

## 功能
通过 HTTP 调用的方式获取昆明配网数据，所有数据查询都通过 DM-kunming.py 的 API 接口完成，不需要直接连接数据库。

## API 服务器
- 地址: http://192.168.113.15:8088
- 所有接口均已由 DM-kunming.py 实现

## 可用接口

### POST 接口（需要传入 JSON body）

| 接口 | 用途 | 参数 |
|------|------|------|
| `/tiaozha` | 跳闸统计（按区域） | `{startTime, endTime}` |
| `/zaohui` | 早会故障统计（瞬时/永久） | `{startTime, endTime}` |
| `/check_qualification` | 受令资格查询 | `{personName}` |
| `/get_abnormal_signals` | 异常信号统计 | `{date}` |
| `/today-chengqu-1h-trip` | 城区一小时跳闸 | `{startTime, endTime}` |
| `/today-baogongdian-trip` | 保供电跳闸 | `{startTime, endTime}` |
| `/overload` | 重过载查询 | `{mode, area, date, days, load_threshold}` |
| `/query` | 执行 SQL 查询 | `{sql}` |
| `/generate-excel` | 生成 Excel 文件 | `{title, content}` |

### GET 接口（需要传入 URL 参数）

| 接口 | 用途 | 参数 |
|------|------|------|
| `/meta` | 查询数据库表结构 | 无 |
| `/svg_groups` | 查询 SVG 分组线路 | `feeder=关键字` |
| `/today-bureau-trip` | 某局跳闸查询 | `bureau=供电局名称`（如"西山局""官渡局"） |

## 调用示例

**跳闸统计：**
```
endpoint="tiaozha"
params={"startTime": "2026-06-29 00:00:00", "endTime": "2026-06-29 23:59:59"}
```

**早会材料：**
```
endpoint="zaohui"
params={"startTime": "2026-06-29 00:00:00", "endTime": "2026-06-29 23:59:59"}
```

**受令资格：**
```
endpoint="check_qualification"
params={"personName": "张良"}
```

**异常信号统计：**
```
endpoint="get_abnormal_signals"
params={"date": "2026-06-29"}
```

**城区一小时跳闸：**
```
endpoint="today-chengqu-1h-trip"
params={"startTime": "2026-06-29 00:00:00", "endTime": "2026-06-29 23:59:59"}
```

**保供电跳闸：**
```
endpoint="today-baogongdian-trip"
params={"startTime": "2026-06-29 00:00:00", "endTime": "2026-06-29 23:59:59"}
```

**重过载汇总：**
```
endpoint="overload"
params={"mode": "total_count", "date": "2026-06-29", "load_threshold": 80}
```

**某局跳闸：**
```
endpoint="today-bureau-trip"
params={"bureau": "西山局"}
```

## 注意事项
- 当 API 返回错误时，看看是不是参数格式有误
- `/tiaozha`、`/zaohui`、`/today-chengqu-1h-trip`、`/today-baogongdian-trip` 都需要 `startTime` 和 `endTime` 两个参数
- `/today-bureau-trip` 需要 `bureau` 参数，不需要时间
- `/get_abnormal_signals` 需要 `date` 参数
- `/overload` 需要 `mode` 参数；其中 `area_count/trend` 需要 `area`，`trend` 可选 `days`，`load_threshold` 默认 80
- 如果 API 服务不可用，技能会返回明确的错误提示
