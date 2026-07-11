# Changelog

## 0.1.0 (2026-07-07)

### Added
- 项目创建，基于 Tornado 的 Gotify 透明文件网关。
- 全 API 透明代理：GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS。
- 文件上传：`multipart/form-data` 拦截，文件保存至 `uploads/<uuid>/<uuid>/` 嵌套目录。
- 安全防护：NFKC 文件名消毒、扩展名白名单校验、MIME 类型检测（python-magic）、SVG CSP 保护。
- URL 重写：消息体使用标记 `{gateway}` 占位，读取时自动替换为公网地址。
- WebSocket 双向中继：`/stream` 透传，含 WebSocket 消息 URL 重写。
- 多语言注入：`</body>` 前注入 i18n 脚本，支持 `zh_CN` locale。
- `/version` 响应注入：JSON 响应增加 `_gateway` 和 `_upload_max` 字段。
- 统一错误格式：`_format_error` 在所有错误路径中生成 `{error, code, backend}`。
- 配置管理：`config.py` 集中管理环境变量，支持 `GOTIFY_BACKEND`、`PUBLIC_URL`、`STORED_MARKER` 等变量。
