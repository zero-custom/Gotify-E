# storage.py — 文件存储引擎

实现文件持久化，附带安全校验（MIME 类型检查、文件名消毒、扩展名白名单）和 Markdown 链接生成。

## 类

### `StoredFile`

`FileStore.save()` 返回的数据类。

| 属性 | 类型 | 说明 |
|---|---|---|
| `marker_url` | `str` | 带标记前缀的 URL，如 `{gateway}/uploads/ab/cd/uuid_photo.png` |
| `markdown` | `str` | 可直接使用的 Markdown：图片用 `![]({marker_url})`，其他用 `[filename]({marker_url})` |

### `FileRejectedError(Exception)`

文件声明图片扩展名但 MIME 类型不是 `image/*` 时抛出。异常消息包含检测到的 MIME 类型。

### `FileStore`

核心存储引擎。在 `app.py` 中模块级实例化：

```python
file_store = FileStore(UPLOAD_DIR, MARKER_PREFIX, IMAGE_EXTS)
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
  │         → 抛出 FileRejectedError
  │
  ├─ 4. 文件名消毒：unicodedata.normalize("NFKC", stem)
  │     → re.sub(r"[^\w.\-]", "_", safe_stem)
  │
  ├─ 5. 生成路径：UUID hex → 子目录 "{hex[:2]}/{hex[2:4]}"
  │     → 文件名 "{uuid}_{safe_stem}{ext}"
  │
  ├─ 6. 写入磁盘：upload_dir / subdir / filename
  │
  └─ 7. 返回 StoredFile：
          marker_url = "{marker_prefix}{subdir}/{filename}"
          markdown   = "![](...)" 图片 / "[name](...)" 非图片
```

## 安全

| 检查 | 时机 | 处理 |
|---|---|---|
| 扩展名格式 | 始终 | 拒绝超长或含非字母数字的扩展名，降级为 `.bin` |
| MIME 不匹配 | 扩展名在 `IMAGE_EXTS` 中 | 若 `magic.from_buffer()` 不返回 `image/*` 则拒绝 |
| 文件名归一化 | 始终 | NFKC 归一化 + 将非 `\w.\-` 字符替换为 `_` |

## 存储结构

```
/data/
├── ab/
│   └── cd/
│       └── a1b2c3d4e5f6_photo.png
├── ef/
│   └── 01/
│       └── 7890abcdef_document.pdf
└── ...
```

路径结构：`{UPLOAD_DIR}/{uuid[:2]}/{uuid[2:4]}/{uuid}_{消毒后文件名}{ext}`。

两级子目录（前 2 + 次 2 个 hex 字符）将文件分布到最多 256×256 = 65,536 个目录中，避免单目录超出文件系统的性能限制。
