# config.py — 配置

## 架构

`config.py` 分为三个部分：

| 部分 | 内容 | 使用方式 |
|---|---|---|
| **EnvConfig** | 环境变量配置（9 个字段） | 应用启动时 `load_env_config()` 构造一次。 |
| **GatewayConfig** | 硬编码设计常量（存储路径、文件安全） | 直接 import：`from config import GatewayConfig` |
| **`load_env_config()`** | 读取环境变量并返回 `EnvConfig` 的工厂函数 | 在 `app.py` 中启动时调用一次 |

## EnvConfig 字段

| 环境变量 | 字段 | 默认值 | 说明 |
|---|---|---|---|
| `GOTIFY_BACKEND` | `gotify_backend` | `http://localhost:8080` | Gotify 后端基础 URL。自动去掉尾部斜杠。 |
| `PUBLIC_HOST` | `public_host` | `""` | 网关公网域名白名单（逗号分隔），用于文件 URL 重写。为空时自动从请求推断。 |
| `HOST` | `host` | `0.0.0.0` | 监听地址。 |
| `PORT` | `port` | `8765` | 监听端口。 |
| `MAX_UPLOAD_MB` | `max_upload_mb` | `50` | 单文件上传上限，单位 MB。 |
| `MAX_FILES_PER_REQUEST` | `max_files_per_request` | `5` | 每次上传请求允许的最大文件数。 |
| `PENDING_TIMEOUT_MINUTES` | `pending_timeout_minutes` | `120` | 文件在 pending 中停留的时间上限，过期删除。 |
| `CLEANUP_INTERVAL_MINUTES` | `cleanup_interval_minutes` | `30` | 定时清理扫描的间隔。 |
| `DELETE_CONCURRENCY` | `delete_concurrency` | `10` | 应用级批量删除时的最大并发 GET 请求数。 |

## GatewayConfig

| 常量 | 值 | 说明 |
|---|---|---|
| `UPLOAD_DIR` | `"/data/upload"` | 永久文件存储目录。用户唯一需要挂载卷的目录。 |
| `STAGING_DIR` | `"/data/staging"` | 上传暂存目录。文件先保存到此，后端确认后再移入 upload_dir。 |
| `PENDING_DIR` | `"/data/pending"` | 待确删除的暂存目录。 |
| `STORED_MARKER` | `"{gateway}"` | 消息体中的存储标记前缀。读取时自动替换为网关地址。 |
| `MAX_FILENAME_BYTES` | `200` | 文件名最大字节长度（超出时截断，保留扩展名）。 |
| `IMAGE_EXTS` | `{".jpg", ".jpeg", ".png", ".gif", ...}` | 视为图片的文件扩展名（消息体中渲染为 `![](...)`）。 |
| `DANGEROUS_EXTS` | `{".html", ".htm", ".js", ...}` | 强制 `Content-Disposition: attachment` 的扩展名，防止浏览器渲染导致 XSS。 |
| `GATEWAY_DIR_NAME` | `"_gateway"` | 网关静态资源（i18n 脚本）目录名。 |

## `__repr__` 安全

`EnvConfig.__repr__` 对敏感字段（`gotify_backend`、`public_host`）用 `"******"` 脱敏，防止凭据在日志中泄露。

## 模块级 vs 类级说明

从 v1.1.0 起，存储路径和 VERSION 从模块级常量或 EnvConfig 移入 GatewayConfig，以明确部署可配参数与架构设计决策之间的边界。
