# Gotify<sup>[E]</sup> — Gotify File Gateway

透明反向代理网关，在标准 Gotify REST API 之上增加文件存储功能。客户端零改动——只需将 Gotify 服务器地址指向网关即可。

## Architecture

```
Gotify 客户端 (curl/App/CLI)
    │ HTTP / WebSocket
    ▼
Gotify<sup>[E]</sup>  ──HTTP──►  Gotify 后端
    │
    ▼
/data/
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `app.py` | 路由注册 + 中间件 + WebSocket 中继 + 入口点 |
| `proxy.py` | `HttpClient` 协议 + `RealHttpClient` + 代理管道 + i18n/版本信息注入 |
| `upload.py` | multipart 上传拦截 + 尽力而为错误策略 |
| `storage.py` | 文件存储引擎：MIME 校验、UUID 嵌套目录、Markdown 链接 |
| `delete_handler.py` | 消息删除拦截 + 关联文件清理 + 启动恢复 |
| `pending_store.py` | 暂存队列管理：manifest 持久化、过期清理、删除失败回滚 |
| `cleanup.py` | 后台定时清理过期暂存文件 |
| `config.py` | `EnvConfig` 部署参数 + `GatewayConfig` 架构常量 |

### 版本演进

| 版本 | 说明 |
|------|------|
| **1.1.2** | 当前版本。i18n 扩展（9 种语言、Intl.RelativeTimeFormat 重构）、布局优化 |
| **1.1.1** | DELETE 全量删除文件清理、暂存目录自动清理、中文翻译补充 |
| **1.1.0** | 安全加固（DANGEROUS_EXTS、SVG CSP sandbox、文件名消毒）、配置重构 |
| **1.0.0** | Tornado → FastAPI 迁移。55+25+42 测试体系建立 |
| **0.1.0** | 初始版本。基于 Tornado 的透明文件网关 |

## Application Setup

### 本地开发

```bash
pip install -r requirements.txt
# 需要 libmagic: brew install libmagic / apt install libmagic1
cp .env.example .env
cd app && uvicorn app:app --reload --port 8765
```

FastAPI 自动提供交互式 API 文档：

```bash
# 启动后打开浏览器访问：
open http://localhost:8765/docs
```

### 测试上传

```bash
curl -F "file=@photo.png" -F "message=test" \
  "http://localhost:8765/message?token=your_token"
curl -F "file=@photo.png" -F "file=@doc.pdf" \
  -F "message=multi" "http://localhost:8765/message?token=your_token"
```

### 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio httpx websockets

# 单元测试（无需外部依赖）
pytest test/ -v -k "not integration"

# 集成测试（需要启动的 Gotify 后端和 Gotify[E] 网关，通过环境变量配置）
export GOTIFY_BACKEND=http://localhost:8080
export GATEWAY_URL=http://localhost:8765
export APP_TOKEN=your_gotify_app_token
export CLIENT_TOKEN=your_gotify_client_token
python3 test/integration_test.py

# 上传场景测试
python3 test/upload_scenarios_test.py
```

测试文件说明：

| 文件 | 类型 | 说明 |
|------|------|------|
| `test/conftest.py` | 共享夹具 | FakeHttpClient、env 初始化、magic mock |
| `test/test_proxy.py` | 单元测试 | 30+ 用例覆盖代理管道全部函数 |
| `test/test_storage.py` | 单元测试 | 8 个用例覆盖 FileStore 完整流程 |
| `test/test_upload.py` | 单元测试 | 9 个用例覆盖上传拦截处理 |
| `test/test_app.py` | 单元测试 | 6 个用例覆盖路由/路径穿越/SVG CSP |
| `test/test_delete.py` | 单元测试 | 35+ 用例覆盖删除/回滚/pending 全流程 |
| `test/integration_test.py` | 集成测试 | 25 个用例连接真实部署，验证基础连通性 + 文件上传 + 静态资源 |
| `test/security_integration_test.py` | 安全集成测试 | 99 个用例覆盖认证矩阵、MIME/扩展名/CSP/文件名/NFKC/马尔可夫转义全部安全措施 |
| `test/upload_scenarios_test.py` | 场景测试 | 42 个用例覆盖 15 种上传组合 + SVG + 路径穿越 + 大文件 + 空文件 |
| `test/delete_integration_test.py` | 删除集成测试 | 51 个用例覆盖单条/多条/批量删除、extras 元数据、文件清理 |

## Usage

### docker-compose

```yaml
services:
  gotify:
    image: gotify/server:latest
    restart: unless-stopped
    ports:
      - 8080:80
    volumes:
      - gotify-data:/app/data

  gateway:
    image: zerocustom/gotify-e:latest
    restart: unless-stopped
    ports:
      - 8765:8765
    environment:
      - GOTIFY_BACKEND=http://gotify:80
      - PUBLIC_URL=http://localhost:8765
    volumes:
      - uploads-data:/data
    depends_on:
      - gotify

volumes:
  gotify-data:
  uploads-data:
```

```bash
docker compose up -d
# 客户端连接 http://localhost:8765 即可
```

### docker cli

```bash
docker run -d --name=gotify-e \
  -p 8765:8765 \
  -e GOTIFY_BACKEND=http://host.docker.internal:8080 \
  -e PUBLIC_URL=http://localhost:8765 \
  -v uploads-data:/data \
  --restart unless-stopped \
  zerocustom/gotify-e:latest
```

## Parameters

| 参数 | 说明 |
|------|------|
| `GOTIFY_BACKEND` | Gotify 后端地址，默认 `http://localhost:8080` |
| `PUBLIC_HOST` | 网关公网域名白名单（逗号分隔）；用于文件 URL 重写，默认自动推断 |
| `HOST` | 监听地址，默认 `0.0.0.0` |
| `PORT` | 监听端口，默认 `8765` |
| `MAX_UPLOAD_MB` | 单文件上传上限 MB，默认 `50` |
| `MAX_FILES_PER_REQUEST` | 每次请求允许上传的最大文件数，默认 `5` |
| `PENDING_TIMEOUT_MINUTES` | 暂存文件超时时间（分钟），默认 `120` |
| `CLEANUP_INTERVAL_MINUTES` | 暂存目录清理间隔（分钟），默认 `30` |
| `DELETE_CONCURRENCY` | 应用删除时并发请求数，默认 `10` |

## Multi-Language UI

网关自动将 Gotify 前端翻译为浏览器的首选语言（支持 **9 种语言**）。

### 自动检测

浏览器 `navigator.language` 自动匹配语言，无需配置：

| 浏览器地区 | 语言 | 翻译文件 |
|---|---|---|
| `zh` / `zh-CN` / `zh-Hans` | 简体中文 | `lang/zh_CN.js` |
| `fr` / `fr-FR` / `fr-CA` | Français | `lang/fr.js` |
| `de` / `de-DE` / `de-AT` | Deutsch | `lang/de.js` |
| `es` / `es-ES` / `es-MX` | Español | `lang/es.js` |
| `pt` / `pt-PT` / `pt-BR` | Português | `lang/pt.js` |
| `ru` / `ru-RU` | Русский | `lang/ru.js` |
| `it` / `it-IT` / `it-CH` | Italiano | `lang/it.js` |
| `ko` / `ko-KR` | 한국어 | `lang/ko.js` |
| `ja` / `ja-JP` | 日本語 | `lang/ja.js` |
| 其他 | English（fallback） | — |

### 手动指定

通过 URL 查询参数强制指定语言：`http://localhost:8765/?lang=de`

语言选择在 `localStorage` 中持久化，刷新页面后保持。

详见 [`docs/i18n.md`](docs/i18n.md)。

## 注意事项

### HTTP 传输层压缩

Gotify[E] **不支持**客户端声明 `Content-Encoding`（如 `gzip`、`deflate`、`br`）进行上传压缩。如果客户端发送 `Content-Encoding` 头，网关返回 `415` 错误。

如需传输层压缩上传，应在网关前部署反向代理（Caddy/nginx）进行处理：

```
客户端 ──Content-Encoding: gzip──► Caddy/nginx ──解压后明文────► Gotify[E]
```

直接上传压缩文件（`.zip`、`.7z`、`.apk`、`.jar`、`.rar`、`.tar.gz` 等）不受影响。

## Support Info

查看日志：

```bash
docker logs -f gotify-e
```

查看版本和上传限制：

```bash
curl http://localhost:8765/version
```

返回示例：

```json
{"version": 3, "_gateway": "Gotify[e]", "_upload_max": 52428800, "_max_files": 5}
```

## Building locally

```bash
git clone <your-repo-url> gotify-e
cd gotify-e
docker build -t gotify-e:latest .
```

## Project Structure

```
├── app/                     # 主程序
│   ├── app.py               # 路由 + 中间件 + WebSocket + 入口点
│   ├── proxy.py             # 代理管道 + HttpClient 协议/实现
│   ├── upload.py            # 上传拦截 + 错误处理
│   ├── storage.py           # 文件存储引擎
│   ├── config.py            # 配置管理 + 版本号常量
│   ├── docker.sh            # 容器引导脚本
│       └── _gateway/            # i18n 多语言 UI 层
│       ├── i18n.js          #   引擎：语言检测 + 文本替换 + Intl 相对时间
│       ├── enhance.js       #   增强：品牌标记 + 布局 + 时间切换按钮
│       └── lang/            #   翻译文件
│           ├── zh_CN.js     #     简体中文（180 条）
│           ├── en.js        #     英语占位
│           ├── fr.js / de.js / es.js / pt.js
│           └── ru.js / it.js / ko.js / ja.js
├── docs/                    # 文档（中英双语）
│   ├── app.md / app.zh.md
│   ├── config.md / config.zh.md
│   ├── i18n.md / i18n.zh.md
│   └── storage.md / storage.zh.md
├── Dockerfile               # 生产镜像构建
├── docker-compose.yml       # 编排部署
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── .dockerignore
├── CHANGELOG.md
└── README.md
```
