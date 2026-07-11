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
/data/ (存储卷，与 /app 分离)
```

### 模块职责

| 模块 | 职责 |
|------|------|
| `app.py` | 路由注册 + 中间件 + WebSocket 中继 + 入口点（约 190 行） |
| `proxy.py` | `HttpClient` 协议 + `RealHttpClient` + 代理管道（请求头过滤 / URL 重写 / i18n 注入 / 网关信息注入） |
| `upload.py` | multipart 上传拦截 + 统一"尽力而为"错误策略 |
| `storage.py` | 文件存储引擎（MIME 校验 / 文件名消毒 / UUID 嵌套目录） |
| `config.py` | 集中配置管理 + 版本号常量 |

### 版本号说明

- **1.0.0** — 当前版本，基于 FastAPI（ASGI 架构）
- **0.1.0** — 前身版本，基于 Tornado（已归档）

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
| `test/test_proxy.py` | 单元测试 | 32 个用例覆盖代理管道全部函数 |
| `test/test_storage.py` | 单元测试 | 8 个用例覆盖 FileStore 完整流程 |
| `test/test_upload.py` | 单元测试 | 9 个用例覆盖上传拦截处理 |
| `test/test_app.py` | 单元测试 | 6 个用例覆盖路由/路径穿越/SVG CSP |
| `test/integration_test.py` | 集成测试 | 25 个用例连接真实部署验证 |
| `test/upload_scenarios_test.py` | 场景测试 | 42 个用例覆盖 15 种上传组合 + 路径穿越 + 大文件 |

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
    build: .
    image: gotify-e:latest
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
  gotify-e:latest
```

## Parameters

| 参数 | 说明 |
|------|------|
| `GOTIFY_BACKEND` | Gotify 后端地址，默认 `http://localhost:8080` |
| `PUBLIC_URL` | 文件公网访问入口；响应中标记被替换为该地址，默认自动检测 |
| `STORED_MARKER` | 消息体中的标记前缀，默认 `{gateway}` |
| `UPLOAD_DIR` | 文件存储路径，默认 `/data` |
| `MAX_UPLOAD_MB` | 单文件上传上限 MB，默认 `50` |
| `HOST` | 监听地址，默认 `0.0.0.0` |
| `PORT` | 监听端口，默认 `8765` |

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
{"version": 3, "_gateway": "Gotify[e]", "_upload_max": 52428800}
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
│   ├── _gateway/            # i18n 本地化脚本
│   └── __init__.py
├── docs/                    # 文档（中英双语）
│   ├── app.md / app.zh.md
│   ├── config.md / config.zh.md
│   └── storage.md / storage.zh.md
├── Dockerfile               # 生产镜像构建
├── docker-compose.yml       # 编排部署
├── requirements.txt         # Python 依赖
├── .env.example             # 环境变量模板
├── .dockerignore
├── CHANGELOG.md
└── README.md
```
