# Changelog

## 1.0.0 (2026-07-09)

### Changed
- 框架从 Tornado 迁移至 FastAPI（ASGI），启动命令改为 `uvicorn app:app`。
- 自动提供交互式 API 文档（访问 `/docs` 端点）。
- 集成测试脚本改用环境变量配置（`GOTIFY_BACKEND`、`GATEWAY_URL`、`APP_TOKEN`、`CLIENT_TOKEN`）。

### Added
- 文件上传 MIME 检测失败时仅跳过该文件，不再中断整个请求。
- FastAPI 生命周期管理，服务关闭时自动释放连接池。
- **55 单元测试**覆盖 proxy/upload/storage/app 四模块，使用 FakeHttpClient 模拟后端、mock magic 避免 C 依赖。
- **25 集成测试**覆盖全部端点，验证文件内容完整性、路径穿越防护、SVG CSP 头等。
- **42 上传场景测试**覆盖 15 种上传组合（纯消息/纯图片/纯文件/混合/多文件/路径穿越/大文件等）。
- **CI/CD**：`.github/workflows/build.yml` 8 平台多架构 Docker 构建工作流。
- 测试配置文档（README.md、AGENTS.md）。

### Fixed
- WebSocket 关闭时正确传播异常，确保客户端连接释放。

## 0.1.0 (2026-07-07)

### Added
- 项目创建，基于 Tornado 的 Gotify 透明文件网关。
- 全 API 透明代理 + 文件上传拦截 + WebSocket 双向中继。
- 多语言注入（i18n），支持 `zh_CN` locale。
- 配置管理：`GOTIFY_BACKEND`、`PUBLIC_URL`、`STORED_MARKER` 等环境变量。
