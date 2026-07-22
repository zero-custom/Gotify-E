# Changelog

## 1.1.2 (2026-07-21)

### Changed
- i18n 扩展至 9 种语言（新增 fr/de/es/pt/ru/it/ko/ja），浏览器自动检测 + `?lang=` 手动指定
- 翻译引擎重构：`i18n.js` 被动化，相对时间改用 `Intl.RelativeTimeFormat`
- 布局优化：`main > main{max-width:50vw!important}` 覆盖 DefaultPage 700px 默认宽度

## 1.1.1 (2026-07-17)

### Fixed
- `DELETE /message`（无 ids）全量删除后未清理已上传文件。网关现在先分页枚举全部消息、收集关联文件移入待删除区，再放行 DELETE。所有 DELETE 路径（单条、批量、应用消息）统一走此事务，删除成功前文件不会丢失。

#### 文件系统优化
- `staging/` 目录：文件确认或取消后自动清理空叶子目录。
- `pending/` 目录：过期文件清理后自动移除空日期目录。

#### i18n
- 补充 34 条 Gotify 新版界面中文翻译（权限提升、表单校验、令牌过期等）。

## 1.1.0 (2026-07-13)

### Changed

#### 安全优化
- SVG 响应头升级为 `sandbox` 指令，阻止脚本执行。
- 新增 `DANGEROUS_EXTS`，危险扩展名强制 `Content-Disposition: attachment`，防 XSS。
- 文件上传增加文件名截断、NFKC 归一化、路径穿越消毒。
- DELETE 请求添加并发控制，避免资源竞争。
- `pending_store.py` 新增路径格式正则校验，拒绝非标准 UUID 嵌套目录路径。
- `proxy.py` 新增代理层 extras 过滤，剥离所有 `gateway::*` 键，防止客户端注入伪造文件字段。

#### 隐私保护
- `repr` 脱敏策略从关键词匹配改为白名单字段，精确控制日志遮蔽范围。

#### 程序可读性
- 配置重构：`GatewayConfig` 与 `EnvConfig` 职责分离，架构常量与部署参数不再混用。

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
