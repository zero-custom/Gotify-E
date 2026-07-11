# config.py — 配置

## 架构

`config.py` 分为三个区：

| 区 | 内容 | 使用方式 |
|---|---|---|
| **PART 1: EnvConfig** | 环境变量配置（7 个字段） | 应用启动时 `load_env_config()` 构造一次。模块级导出常量供直接 import。 |
| **PART 2: GatewayConfig** | 硬编码可调参数（图片扩展名、网关目录名） | 需要时 import：`from config import GatewayConfig` |
| **PART 3: 派生常量** | 从 EnvConfig + GatewayConfig 计算得到 | `MAX_UPLOAD`、`UPLOAD_DIR`（Path）、`GATEWAY_DIR`、`MARKER_PREFIX` — 作为模块级常量导出 |

## EnvConfig 字段（PART 1）

| 环境变量 | 字段 | 默认值 | 说明 |
|---|---|---|---|
| `GOTIFY_BACKEND` | `gotify_backend` | `http://localhost:8080` | Gotify 后端基础 URL。自动去掉尾部斜杠。 |
| `PUBLIC_URL` | `public_url` | `""` | 网关公网地址，用于文件 URL 重写。为空时从请求头自动推断。 |
| `HOST` | `host` | `0.0.0.0` | 监听地址。 |
| `PORT` | `port` | `8765` | 监听端口。 |
| `UPLOAD_DIR` | `upload_dir` | `/data` | 文件上传存储路径。与 `/app` 分离实现算存分离。 |
| `STORED_MARKER` | `stored_marker` | `{gateway}` | 消息体中的存储标记前缀。读取时自动替换为 `PUBLIC_URL`。 |
| `MAX_UPLOAD_MB` | `max_upload_mb` | `50` | 单文件上传上限，单位 MB。 |

## GatewayConfig（PART 2）

| 常量 | 值 | 说明 |
|---|---|---|
| `IMAGE_EXTS` | `{".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico"}` | 视为图片的文件扩展名（消息体中渲染为 `![](...)`）。 |
| `GATEWAY_DIR_NAME` | `"_gateway"` | 网关静态资源（i18n 脚本）目录名。 |

## 派生常量（PART 3）

| 常量 | 计算方式 | 示例值 |
|---|---|---|
| `BASE_DIR` | `Path(__file__).parent.resolve()` | `/app` |
| `cfg` | `load_env_config()` | `EnvConfig(...)` |
| `BACKEND` | `cfg.gotify_backend` | `http://localhost:8080` |
| `PUBLIC_URL` | `cfg.public_url` | `http://example.com:8765` |
| `HOST` | `cfg.host` | `0.0.0.0` |
| `PORT` | `cfg.port` | `8765` |
| `UPLOAD_DIR` | `Path(cfg.upload_dir)` | `Path("/data")` |
| `GATEWAY_DIR` | `BASE_DIR / GATEWAY_DIR_NAME` | `Path("/app/_gateway")` |
| `MAX_UPLOAD` | `cfg.max_upload_mb * 1024 * 1024` | `52428800` |
| `IMAGE_EXTS` | `GatewayConfig.IMAGE_EXTS` | `{".png", ".jpg", ...}` |
| `STORED_MARKER` | `cfg.stored_marker` | `{gateway}` |
| `MARKER_PREFIX` | `{stored_marker}/uploads/` | `{gateway}/uploads/` |

## 使用

```python
# 模块只 import 自己需要的
from config import BACKEND, UPLOAD_DIR, MAX_UPLOAD

# 或导入完整 cfg 对象进行程序化访问
from config import cfg
# cfg.host, cfg.port, cfg.max_upload_mb, ...
```

## `__repr__` 安全

`EnvConfig.__repr__` 自动屏蔽字段名包含 `password` 或 `secret`（不区分大小写）的值——非空时显示 `"******"` 而非真实值。
