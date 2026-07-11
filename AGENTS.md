# Gotify<sup>[E]</sup> — 代理指南

## 项目概要

FastAPI 反向代理网关，为 Gotify 增加文件存储能力。客户端只需将 Gotify 地址指向网关，无需任何配置变更。

- **版本号**：`1.0.0`（定义在 `app/config.py:VERSION`）
- **Python**：3.14+（Docker 使用 Alpine）
- **端口**：8765
- **入口点**：`app/app.py:main()` → `uvicorn app:app`

## 开发命令

```bash
# 前置依赖
apt install libmagic1        # python-magic 的 C 库依赖
pip install -r requirements.txt

# 启动开发服务器（带自动重载）
cd app && uvicorn app:app --reload --port 8765

# 或通过模块入口点启动
cd app && python3 app.py
```

FastAPI 自动提供交互式 API 文档：`http://localhost:8765/docs`。

## 测试

**55 单元测试** + **25 集成测试** + **42 场景测试**，共 122 个用例。详见项目根目录 `test/`。

### 单元测试（无需外部依赖）

```bash
pytest test/ -v -k "not integration"
```

使用 `FakeHttpClient`（FIFO 响应队列）模拟后端，`magic` 模块全局 mock 避免 libmagic C 依赖。

### 集成测试（需部署环境）

```bash
export GOTIFY_BACKEND=http://gotify:8080
export GATEWAY_URL=http://localhost:8765
export APP_TOKEN=...
export CLIENT_TOKEN=...
python3 test/integration_test.py
python3 test/upload_scenarios_test.py
```

### 关键测试模式

- `conftest.py` 在模块级设置 env vars，确保 `config.py` 导入时读到测试值
- `FakeHttpClient` 耗尽 FIFO 队列后自动抛出 `httpx.RequestError`，覆盖 502 路径
- 集成测试使用若干随机下载的真实文件（PNG/JPEG/WEBP/GIF/SVG/TXT/PDF/CSV）验证内容完整性
- 路径穿越测试覆盖 5 种攻击向量：`../../../`、`%252f`、`....//`、反斜杠、`%2e%2e`

无 lint/formatter 配置（无 `pyproject.toml`、`ruff` 等）。

## 架构

```
app/
  app.py        路由 + WebSocket 中继 + 入口点（约 190 行）
  proxy.py      HttpClient 协议 + RealHttpClient + 代理管道（请求头过滤、URL 重写、i18n/版本信息注入）
  upload.py      multipart 上传拦截，尽力而为错误策略
  storage.py    文件存储：MIME 校验、UUID 嵌套目录、Markdown 链接生成
  config.py     EnvConfig 数据类 + 模块级计算常量 + VERSION
  docker.sh     容器入口脚本，支持运行时安装包（通过环境变量）
  _gateway/     i18n JS 文件（en.js, zh_CN.js）
```

注意：`config.py` 的**模块级常量**在导入时计算（`BACKEND`、`PUBLIC_URL`、`UPLOAD_DIR` 等）。编写测试或实例化类时，应直接传入 `EnvConfig` 对象，而非依赖这些全局常量。

## 路由

| 路径 | 功能 |
|------|------|
| `GET /uploads/{path}` | 提供上传文件服务，含路径穿越防护 |
| `GET/DELETE/PUT /message` | 透明代理至 Gotify 后端 |
| `POST /message` | 拦截 multipart 上传，保存文件，将 JSON 代理至 Gotify |
| `WebSocket /stream` | 双向中继，含文件 URL 重写 |
| `/{path:path}`（兜底） | 所有其他请求透明代理 |
| `/_gateway/*` | 静态 i18n JS 资源 |
| `/docs` | FastAPI 自动生成的 OpenAPI 文档 |
| `/version` | 代理至后端，注入 `_gateway` + `_upload_max` 字段 |

## 关键模式

- **`HttpClient` 协议**（`proxy.py`）— 可注入，便于测试。`RealHttpClient` 封装 `httpx.AsyncClient`（超时 120s，连接超时 10s，连接池 50/100）。
- **`FileStore`** 构造函数接收 `(upload_dir, marker_prefix, image_exts)` — 可注入。
- **无数据库** — 除文件系统外无持久化层。
- **i18n 注入** 使用 `html.parser` DOM 方式（非正则）。若未找到 `</body>` 则静默跳过。
- **上传错误策略**：尽力而为——单个文件被拒不会中断整个上传。
- **错误格式**：所有错误返回 `{"error": "...", "code": N}`（代理错误可选附加 `"backend"` 字段）。

## 注意事项

- `libmagic` 是 C 语言依赖，必须通过系统包管理器安装（`apt install libmagic1`）。
- `python-multipart` 是 FastAPI 表单解析的运行时依赖（已包含在 `requirements.txt`）。
- Docker `HEALTHCHECK` 访问 `/version` 端点——该端点若失效，容器会被标记为不健康。
- `docker.sh` 支持运行时通过环境变量安装包：`INSTALL_PACKAGES`（Alpine apk）和 `INSTALL_PIP_PACKAGES`（pip），使用管道符 `|` 分隔，例如 `INSTALL_PACKAGES="curl|vim"`。
- SVG 文件在上传时会获得 `Content-Security-Policy: script-src 'none'` 响应头。
- WebSocket 出站连接使用 `websockets.connect(url)` — 仅入站端使用 FastAPI WebSocket。
- CI/CD 由 `.github/workflows/build.yml` 提供（Docker 多架构构建，从 `alter_upnpd` 移植）。
- 不支持 `Content-Encoding` 上传压缩（`gzip`/`deflate`/`br`），客户端发送返回 415。需要时在前端代理层（Caddy/nginx）解压。
- `.dockerignore` 排除了 `test/`、`docs/`、`CHANGELOG.md`、`README.md`、`.github/`（生产镜像不含测试和文档）。
