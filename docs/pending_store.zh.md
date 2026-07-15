# pending_store.py — 待清理文件状态机

管理 DELETE 拦截期间移动到 pending 目录的文件。提供仅追加的 manifest 操作日志、文件移动/恢复和基于时间的过期清理。

## 安全防护

### 路径格式校验

`move_to_pending` 对每个传入的 `path` 做正则校验 `^[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{32}_.+$`，仅允许 `storage.py` 生成的 UUID 嵌套目录结构。不匹配的路径被拒绝并记警告——防止通过 `gateway::files` 注入任意路径。

### 路径穿越防护

`move_to_pending` 和 `restore` 均使用 `Path.resolve()` 解析目标路径，并确认其在 `upload_dir` 范围内。`../../../etc/passwd` 等穿越载荷在文件操作前被拦截。

### 代理层 extras 过滤

`proxy.py` 在每次代理转发的 JSON 请求体中剥离所有 `gateway::*` 键。配合路径格式校验，确保只有 `upload.py` 中的 multipart 上传处理器可以合法创建 `gateway::files` 条目。

## 类：`PendingStore`

在 `delete_handler.py` 中实例化为 `_store`：

```python
_store = PendingStore(upload_dir, pending_dir, pending_timeout_seconds)
```

### Manifest 格式

存储在 `{pending_dir}/manifest.jsonl`，每行一个 JSON 对象：

```jsonl
{"msg_id":1,"orig_path":"ab/cd/abc_photo.png","pending_path":"20260709/ab_cd_abc_photo.png","time":"2026-07-09T12:00:00","status":"moved"}
{"msg_id":2,"orig_path":"ef/01/def_doc.pdf","pending_path":"20260709/ef_01_def_doc.pdf","time":"2026-07-09T12:01:00","status":"deleted"}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `msg_id` | int | Gotify 消息 ID |
| `orig_path` | str | 相对于 `upload_dir` 的路径（移动前来源） |
| `pending_path` | str | 相对于 `pending_dir` 的路径（移动后目标） |
| `time` | str | 条目创建时间的 ISO 8601 时间戳 |
| `status` | str | `moved`（DELETE 尚未确认）/ `deleted`（DELETE 已确认） |

### 方法

#### `move_to_pending(msg_id, files) -> list[dict]`

将文件从 `upload_dir` 移动到 `pending_dir/{date}/`。使用 `shutil.move()` 实现跨文件系统安全。

| 情况 | 行为 |
|---|---|
| 文件存在 | `shutil.move` → 添加条目到返回值 |
| 文件不存在 | 记录警告，静默跳过 |
| `path` 为空 | 静默跳过 |
| `OSError` | 记录错误，条目不包含在该次结果中 |

同批次文件共享一个日期子目录（`YYYYMMDD`）。展平文件名将 `/` 替换为 `_`，避免在 pending 中产生嵌套子目录。

#### `restore(entries)`

还原 `move_to_pending`——将文件从 `pending_dir` 移回 `upload_dir`。pending 中缺失的文件静默跳过。

#### `append_manifest(msg_id, moved)`

向 `manifest.jsonl` 追加条目。每条记录均带有时间戳，初始状态为 `status: "moved"`。

#### `read_manifest() -> list[dict]`

读取 `manifest.jsonl` 所有条目。文件不存在或为空时返回空列表。损坏的 JSON 行静默丢弃。

#### `update_status(msg_ids, new_status)`

更新所有匹配任一 `msg_id` 的条目的 `status` 字段。原子性地重写整个 manifest 文件。manifest 不存在时无操作。

#### `remove_entries(msg_ids)`

删除 `msg_id` 在给定列表中的所有条目。原子性地重写整个 manifest 文件。

#### `clean_expired(now=None)`

扫描 manifest，删除超过 `pending_timeout_seconds` 的条目。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `now` | `time.time()` | 注入参考时间戳，便于确定性测试 |

每条过期条目：删除 pending 文件（`Path.unlink(missing_ok=True)`）并丢弃 manifest 记录。未过期的条目保留。

**原子性 manifest 写入**：所有重写 manifest 的方法（`update_status`、`remove_entries`、`clean_expired`）使用 tmpfile + `os.replace()` 模式。新内容写入同一目录的 `.tmp` 文件，然后原子性地覆盖原文件。这可以防止崩溃后读取到部分损坏的 manifest。

## 目录结构

```
upload_dir/
├── ab/cd/uuid_photo.png          ← 正常的存储文件
└── ...

pending_dir/                      ← 首次移动时创建
├── manifest.jsonl                ← 仅追加的操作日志
└── 20260709/
    ├── ab_cd_uuid_photo.png      ← 已移动文件（展平路径）
    └── ...
```
