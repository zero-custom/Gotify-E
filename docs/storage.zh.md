# storage.py — 文件存储引擎

实现文件持久化，附带安全校验（MIME 类型检查、文件名消毒）和 Markdown 链接生成。

## 类

### `StoredFile`

`FileStore.save()` 返回的数据类。

| 属性 | 类型 | 说明 |
|---|---|---|
| `marker_url` | `str` | 带标记前缀的 URL，如 `{gateway}/uploads/ab/cd/uuid_photo.png` |
| `markdown` | `str` | 可直接使用的 Markdown：图片用 `![]({marker_url})`，其他用 `[name]({marker_url})` |
| `uuid` | `str` | UUID hex（用作文件标识符） |
| `path` | `str` | 上传目录内的相对路径：`{subdir}/{uuid}_{safe_stem}{ext}` |
| `size` | `int` | 文件大小（字节） |
| `original_name` | `str` | 客户端提供的原始文件名 |

### `FileStore`

核心存储引擎。在 `app.py` 中模块级实例化：

```python
file_store = FileStore(UPLOAD_DIR, MARKER_PREFIX, IMAGE_EXTS, STAGING_DIR)
```

#### `save(filename: str, body: bytes) -> StoredFile`

持久化文件并返回 StoredFile 描述符。保存管道：

```
save(filename, body)
  │
  ├─ 1. 从文件名提取 stem 和扩展名
  │
  ├─ 2. 校验扩展名：/^\.[a-zA-Z0-9]{1,10}$/
  │     └── 失败 → 降级为 ".bin"
  │
  ├─ 3. MIME 检查：magic.from_buffer(body, mime=True)
  │     └── 扩展名在 IMAGE_EXTS 中且 MIME 不以 "image/" 开头
  │         → 重命名为 ".bin"（不拒绝，文件不会丢失）
  │     └── MIME 检测失败（magic 异常）
  │         → 重命名为 ".bin"（优雅降级）
  │
  ├─ 4a. 文件名消毒：unicodedata.normalize("NFKC", stem)
  │      → re.sub(r"[^\w.\-]", "_", safe_stem)
  │
  ├─ 4b. 截断至 MAX_FILENAME_BYTES（200 字节）：
  │      按 UTF-8 编码，在字节边界截断（不破坏多字节字符），重新解码。保留扩展名。
  │
  ├─ 5. 生成路径：UUID hex → 子目录 "{hex[:2]}/{hex[2:4]}"
  │     → 文件名 "{uuid}_{safe_stem}{ext}"
  │
  ├─ 6. 写入 staging 目录：staging_dir / subdir / filename
  │
  └─ 7. 返回 StoredFile：
          marker_url = "{marker_prefix}{subdir}/{filename}"
          markdown   = markdown_escape("[name](...)" 或 "![](...)")
```

**Markdown 转义**：生成的 `markdown` 字段对字符 `\`、`[`、`]`、`(`、`)` 进行反斜杠转义，防止 Markdown 渲染器将文件 URL 解析为格式化语法。`marker_url` 不做转义——仅转义 Markdown 表示。

#### `confirm(stored: StoredFile) -> None`

将单个确认文件从 staging 目录移至永久 `upload_dir`。在 Gotify 后端返回 2xx 后调用。

```python
# staging/<uuid[:2]>/<uuid[2:4]>/<uuid>_photo.png
#   → upload/<uuid[:2]>/<uuid[2:4]>/<uuid>_photo.png
```

使用 `shutil.move` 实现跨文件系统安全。若 staging 文件不存在则静默跳过。

#### `cancel(stored: StoredFile) -> None`

删除单个 staging 文件及其元数据。在 Gotify 后端返回非 2xx 后调用。

#### `_rmdir_parents(path: Path) -> None`（静态方法）

文件移出/删除后清理空叶子目录及其父目录。使用 `Path.rmdir()`，仅在目录为空时成功——非空时安全无操作。`confirm()` 和 `cancel()` 在文件操作完成后均会调用。

```
staging/ab/cd/uuid_photo.png  →  leaf = staging/ab/cd/
  ├─ rmdir(staging/ab/cd/)    ← 空则成功
  └─ rmdir(staging/ab/)       ← 空则成功
```

## 安全

| 检查 | 时机 | 处理 |
|---|---|---|
| 扩展名格式 | 始终 | 拒绝超长或含非字母数字的扩展名，降级为 `.bin` |
| MIME 不匹配 | 扩展名在 `IMAGE_EXTS` 中 | 重命名为 `.bin` 并保存（不拒绝——数据永不丢失） |
| MIME 检测失败 | 始终 | 重命名为 `.bin` 并保存（优雅降级） |
| 文件名归一化 | 始终 | NFKC 归一化 + 将非 `\w.\-` 字符替换为 `_` |
| 文件名截断 | 始终 | UTF-8 安全截断至 200 字节 |
| Markdown 转义 | 始终 | 对 `\` `[` `]` `(` `)` 做反斜杠转义 |

## 存储结构

```
/data/
├── upload/
│   ├── ab/cd/                  ← UUID 子目录（永久存储）
│   │   └── uuid_photo.png
│   └── ...
├── staging/                    ← 上传中暂存目录
│   ├── ab/cd/                  ← 镜像相同的 UUID 子目录结构
│   │   └── uuid_photo.png
│   └── ...
└── pending/                    ← 待处理 DELETE 目录（参见 pending_store.md）
    ├── manifest.jsonl
    └── ...
```

**上传/staging 流程**：`save()` 写入 `staging_dir/{uuid[:2]}/{uuid[2:4]}/{uuid}_{stem}{ext}`。Gotify 后端确认消息 POST（2xx）后，`confirm()` 将文件移至 `upload_dir/{uuid[:2]}/{uuid[2:4]}/`。失败时 `cancel()` 删除 staging 文件。

所有目录的路径结构：`{BASE_DIR}/{uuid[:2]}/{uuid[2:4]}/{uuid}_{消毒后文件名}{ext}`。

两级子目录（前 2 + 次 2 个 hex 字符）将文件分布到最多 256×256 = 65,536 个目录中，避免单目录超出文件系统的性能限制。
