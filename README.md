# Gotify[E] — Gotify File Gateway

透明反向代理网关，在标准 Gotify REST API 之上增加文件存储功能。客户端零改动——只需将 Gotify 服务器地址指向网关即可。

## Application Setup

Gotify[E] 监听 HTTP 端口（默认 8765），透明转发全部 API 请求到 Gotify 后端。拦截 `POST /message` 的 `multipart/form-data` 上传，文件存入本地目录，消息正文自动追加 Markdown 链接。

```
Gotify 客户端 (curl/App/CLI)
    │ HTTP / WebSocket
    ▼
Gotify[E]  ──HTTP──►  Gotify 后端
    │
    ▼
/data/ (存储卷，与 /app 分离)
```

### 本地开发

```bash
pip install -r requirements.txt
# 需要 libmagic: brew install libmagic / apt install libmagic1
cp .env.example .env
UPLOAD_DIR=./data cd app && python3 app.py
```

### 测试上传

```bash
curl -F "file=@photo.png" -F "message=test" \
  "http://localhost:8765/message?token=your_token"
curl -F "file=@photo.png" -F "file=@doc.pdf" \
  -F "message=multi" "http://localhost:8765/message?token=your_token"
```

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
| `UPLOAD_DIR` | 文件存储路径，默认 `/data`（存算分离） |
| `MAX_UPLOAD_MB` | 单文件上传上限 MB，默认 `50` |
| `HOST` | 监听地址，默认 `0.0.0.0` |
| `PORT` | 监听端口，默认 `8765` |

## Support Info

查看日志：

```bash
docker logs -f gotify-e
```

查看版本和上传限制：

```bash
curl http://localhost:8765/version
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
│   ├── app.py               # 入口：路由 + 代理 + 消息处理 + WebSocket
│   ├── config.py            # 全局配置管理（环境变量）
│   ├── storage.py           # 文件存储引擎（MIME 校验 / 消毒 / UUID 嵌套）
│   ├── docker.sh            # 容器引导脚本
│   ├── _gateway/            # i18n 本地化脚本
│   └── __init__.py
├── docs/                    # 文档（模块文档中英双语）
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
