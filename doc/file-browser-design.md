# Infra Monitor 在线文件浏览器设计方案

## 1. 背景与目标

Infra Monitor 当前提供 ZooKeeper、Kafka、Elasticsearch 三类基础设施监控能力。新增“在线文件浏览器”作为同级功能模块，目标是在 Web 页面中以只读方式浏览服务器文件系统，并在线查看常见文本文件内容，方便运维排查配置、日志、脚本和部署产物。

本模块定位为“只读诊断工具”，首版不提供上传、编辑、删除、移动、重命名等写操作。

## 2. 功能范围

### 首版功能

- 顶部导航增加“文件浏览器”菜单，与 ZooKeeper、Kafka、Elasticsearch 同级。
- 文件浏览页展示当前目录路径、上级目录入口、子目录和文件列表。
- 页面顶部展示当前访问根目录，支持手动输入根目录并打开。
- 支持点击目录进入下级目录。
- 支持返回上级目录和刷新当前目录。
- 支持点击文件查看内容。
- 文本文件以内嵌代码块方式在线查看。
- Python、SQL、Bash 与 JSON 文本文件支持基础语法高亮。
- 图片文件以内嵌图片方式在线查看，支持 PNG、JPEG、GIF、WebP、AVIF、APNG 和 SVG。
- 二进制文件、超大文件或不支持预览的文件显示元信息和不可预览提示。
- 支持基础文件信息展示：名称、类型、大小、修改时间。
- 支持通过配置限定允许访问的根目录。
- 支持左右分栏展示文件列表和预览区域，分栏宽度可拖拽调整并保存在浏览器 `localStorage`。

### 暂不包含

- 文件编辑、上传、删除、重命名、移动。
- 文件下载。
- 压缩包在线解压。
- PDF、Office 等富媒体预览。
- 多服务器远程浏览。

## 3. 安全设计

文件浏览能力风险较高，首版必须坚持只读和路径边界。

### 访问根目录

新增配置项：

```json
{
  "file_browser": {
    "root": ".",
    "max_preview_bytes": 262144,
    "enabled": true
  }
}
```

- `root` 默认指向项目根目录，也可通过页面输入框或 API `root` 参数临时切换。
- 页面和 API 支持通过 `root` query 参数临时切换浏览根目录。
- 所有前端传入路径都必须解析为 `root` 下的真实路径。
- 不允许通过 `..`、符号链接或绝对路径逃逸出 `root`。
- `enabled` 可关闭文件浏览器；关闭后页面和 API 不再暴露浏览能力。

### 路径校验

后端服务层统一提供路径解析函数：

- 接收相对路径，例如 `logs/app.log`。
- 使用 `Path.resolve()` 得到真实路径。
- 校验真实路径是否等于 root 或位于 root 内。
- 不满足条件时返回 403 或业务错误。

### 文件预览限制

- 只预览普通文件。
- 默认最多读取 `max_preview_bytes` 字节。
- 优先按 UTF-8 解码，失败后尝试系统默认容错解码。
- 发现 NUL 字节或明显二进制内容时不展示正文。
- 大于预览上限的文件只显示前 `max_preview_bytes` 内容，并提示已截断。
- 图片预览通过独立接口返回文件流，但仍必须复用相同的根目录和路径逃逸校验。

### 权限与审计

当前项目尚未引入登录认证，因此该模块默认只适合可信内网环境。后续生产化前建议增加：

- 登录认证。
- 只读/管理员角色。
- 文件访问审计日志。
- 敏感路径 denylist，例如 `.env`、密钥目录、证书目录。

## 4. 后端设计

### 模块结构

建议新增：

```text
app/
  routers/
    files.py
  services/
    file_service.py
  templates/
    files.html
```

### 数据模型

可复用 dict 返回，也可在 `app/models.py` 增加 dataclass：

- `FileEntry`
  - `name`
  - `path`
  - `is_dir`
  - `size`
  - `modified`
  - `extension`
  - `preview_type`
  - `language`
- `FilePreview`
  - `path`
  - `name`
  - `size`
  - `modified`
  - `content`
  - `encoding`
  - `truncated`
  - `previewable`
  - `preview_type`
  - `mime_type`
  - `language`
  - `error`

### 页面路由

- `GET /files/`
  - 渲染文件浏览器页面。
  - query 参数：`path`，默认空字符串表示根目录。
  - query 参数：`root`，为空时使用配置中的 `file_browser.root`。

### API 路由

- `GET /files/api/list?path=...`
  - 返回目录列表。
- `GET /files/api/preview?path=...`
  - 返回文件预览元信息。文本文件包含正文；Python/SQL/Bash/JSON 文件额外返回 `language`；图片文件返回 `preview_type=image` 和 MIME 类型。
- `GET /files/api/image?path=...`
  - 返回已通过路径校验和类型校验的图片文件流。

以上 API 均支持 `root` query 参数，并复用同一套路径边界校验。

### 服务层职责

`FileBrowserService` 负责：

- 加载 `file_browser` 配置。
- 解析并校验路径边界。
- 列出目录内容。
- 读取文件元信息。
- 判断是否可预览。
- 安全读取文本内容。
- 识别 Python、SQL、Bash、JSON 文件类型，供前端执行语法高亮。
- 校验图片类型并返回图片文件路径和 MIME 类型。

路由层只负责参数接收、异常映射、模板渲染和 JSON 返回。

## 5. 前端设计

### 导航

在 `base.html` 增加菜单：

- 文案：文件浏览器
- 图标：Bootstrap Icons 中可使用 `bi-folder2-open`
- 链接：`{{ root_path }}/files/`
- active 判断：当前路径包含 `/files`

### 页面布局

`files.html` 建议采用左右布局：

- 顶部：当前根目录、根目录输入框、打开按钮、刷新按钮。
- 左侧/主区域：目录和文件表格。
- 右侧或下方：文件预览区域。
- 中间：可拖拽分隔条，用于调整文件列表和预览区域宽度；桌面端保存用户调整后的左侧宽度。

表格列：

- 名称
- 类型
- 大小
- 修改时间

交互：

- 点击目录：跳转到对应 `path`。
- 点击文件：通过 fetch 调用 preview API，按 `preview_type` 更新文本或图片预览区域；文本预览按 `language` 对 Python、SQL、Bash、JSON 做基础语法高亮。
- 图片预览：先通过 preview API 获取元信息，再通过 image API 以内联方式加载文件流。
- 错误状态：显示无法访问、不可预览、读取失败原因。

## 6. 当前能力摘要

文件浏览器是面向运维排查的轻量级在线文件查看器，适合快速查看配置、日志、脚本、部署产物和图片资源。当前实现刻意保持只读，不提供编辑、上传、删除、重命名、移动或下载能力。

核心能力：

- 浏览配置根目录下的目录和文件。
- 进入子目录、返回上级目录、刷新当前目录。
- 在页面右侧预览文件内容。
- 按配置上限读取文本，超过 `max_preview_bytes` 时提示已截断。
- 对 Python、SQL、Bash、JSON 做基础语法高亮。
- 以内嵌方式预览 PNG、JPEG、GIF、WebP、AVIF、APNG、SVG 图片。
- 对二进制文件或不支持预览的文件仅展示元信息和不可预览提示。
- 展示名称、类型、大小、修改时间。
- 通过配置或页面输入选择访问根目录。
- 支持左右分栏拖拽调整，并持久化到浏览器本地存储。

安全约束：

- 只允许访问配置根目录或临时选择根目录下的相对路径。
- 拒绝绝对路径。
- 拒绝 `../` 路径穿越。
- 拒绝或过滤指向根目录外的符号链接。
- 可通过 `file_browser.enabled` 关闭功能。
- 可通过 `file_browser.max_preview_bytes` 控制最大预览字节数。

## 7. 配置补齐

`DEFAULT_CONFIG` 增加 `file_browser` 配置后，需要确保 SQLite 中缺少该段配置时仍能通过 deep merge 自动补齐默认值。

测试需覆盖：

- 缺少 `file_browser` 时自动补齐默认值。
- 自定义 `file_browser.root` 后仍保留 `max_preview_bytes` 默认值。

## 8. 测试方案

### 单元测试

新增或维护 `tests/test_file_service.py`：

- 能列出根目录文件。
- 能进入子目录。
- 路径穿越被拒绝。
- 超大文件预览被截断。
- 二进制文件不返回正文。
- UTF-8 文本文件可正确预览。
- Python、SQL、Bash、JSON 文件返回对应 `language` 标记。
- 图片文件返回图片预览类型、MIME 类型，并能通过图片接口读取。

### 路由测试

通过 `tests/test_files_router.py` 覆盖 FastAPI `TestClient` 场景：

- `/files/` 返回 200。
- `/files/api/list` 返回目录 JSON。
- `/files/api/preview` 返回文件预览 JSON。
- `/files/api/image` 返回图片文件流。
- 非法路径返回 403 或错误 JSON。

### 回归测试

- `uv run ruff check .`
- `uv run pytest -q`
- `docker compose config --quiet`

## 9. 实施步骤

1. 扩展默认配置，加入 `file_browser`。
2. 新增 `FileBrowserService`，实现安全路径解析、目录列表、文件预览。
3. 新增 `files` router 和模板页面。
4. 在 `main.py` 注册 router。
5. 在 `base.html` 增加同级导航菜单。
6. 增加服务层测试和必要的路由测试。
7. 运行 lint、pytest、compose 配置校验。

## 10. 后续扩展

- 增加文件下载能力，但需加权限和审计。
- 增加文件搜索能力，限制搜索根目录和最大扫描规模。
- 增加日志文件 tail 模式。
- 扩展更多语言的语法高亮。
- 增加 Markdown 预览。
- 增加多服务器/多根目录切换。
