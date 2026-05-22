# Infra Monitor 在线文件浏览器设计方案

## 1. 背景与目标

Infra Monitor 当前提供 ZooKeeper、Kafka、Elasticsearch 三类基础设施监控能力。新增“在线文件浏览器”作为同级功能模块，目标是在 Web 页面中以只读方式浏览服务器文件系统，并在线查看常见文本文件内容，方便运维排查配置、日志、脚本和部署产物。

本模块定位为“只读诊断工具”，首版不提供上传、编辑、删除、移动、重命名等写操作。

## 2. 功能范围

### 首版功能

- 顶部导航增加“文件浏览器”菜单，与 ZooKeeper、Kafka、Elasticsearch、配置同级。
- 文件浏览页展示当前目录路径、上级目录入口、子目录和文件列表。
- 支持点击目录进入下级目录。
- 支持点击文件查看内容。
- 文本文件以内嵌代码块方式在线查看。
- 二进制文件、超大文件或不支持预览的文件显示元信息和不可预览提示。
- 支持基础文件信息展示：名称、类型、大小、修改时间。
- 支持通过配置限定允许访问的根目录。

### 暂不包含

- 文件编辑、上传、删除、重命名、移动。
- 文件下载。
- 压缩包在线解压。
- 图片、PDF、Office 等富媒体预览。
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

- `root` 默认指向项目根目录，后续可在配置页扩展为可编辑项。
- 所有前端传入路径都必须解析为 `root` 下的真实路径。
- 不允许通过 `..`、符号链接或绝对路径逃逸出 `root`。

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
- `FilePreview`
  - `path`
  - `name`
  - `size`
  - `modified`
  - `content`
  - `encoding`
  - `truncated`
  - `previewable`
  - `error`

### 页面路由

- `GET /files/`
  - 渲染文件浏览器页面。
  - query 参数：`path`，默认空字符串表示根目录。

### API 路由

- `GET /files/api/list?path=...`
  - 返回目录列表。
- `GET /files/api/preview?path=...`
  - 返回文件预览。

### 服务层职责

`FileBrowserService` 负责：

- 加载 `file_browser` 配置。
- 解析并校验路径边界。
- 列出目录内容。
- 读取文件元信息。
- 判断是否可预览。
- 安全读取文本内容。

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

- 顶部：当前路径面包屑、刷新按钮。
- 左侧/主区域：目录和文件表格。
- 右侧或下方：文件预览区域。

表格列：

- 名称
- 类型
- 大小
- 修改时间

交互：

- 点击目录：跳转到对应 `path`。
- 点击文件：通过 fetch 调用 preview API，更新预览区域。
- 错误状态：显示无法访问、不可预览、读取失败原因。

## 6. 配置兼容

`DEFAULT_CONFIG` 增加 `file_browser` 配置后，需要确保旧 `config.json` 仍能通过 deep merge 自动补齐默认值。

测试需覆盖：

- 缺少 `file_browser` 时自动补齐默认值。
- 自定义 `file_browser.root` 后仍保留 `max_preview_bytes` 默认值。

## 7. 测试方案

### 单元测试

新增或维护 `tests/test_file_service.py`：

- 能列出根目录文件。
- 能进入子目录。
- 路径穿越被拒绝。
- 超大文件预览被截断。
- 二进制文件不返回正文。
- UTF-8 文本文件可正确预览。

### 路由测试

通过 `tests/test_files_router.py` 覆盖 FastAPI `TestClient` 场景：

- `/files/` 返回 200。
- `/files/api/list` 返回目录 JSON。
- `/files/api/preview` 返回文件预览 JSON。
- 非法路径返回 403 或错误 JSON。

### 回归测试

- `uv run ruff check .`
- `uv run pytest -q`
- `docker compose config --quiet`

## 8. 实施步骤

1. 扩展默认配置，加入 `file_browser`。
2. 新增 `FileBrowserService`，实现安全路径解析、目录列表、文件预览。
3. 新增 `files` router 和模板页面。
4. 在 `main.py` 注册 router。
5. 在 `base.html` 增加同级导航菜单。
6. 增加服务层测试和必要的路由测试。
7. 运行 lint、pytest、compose 配置校验。

## 9. 后续扩展

- 增加文件下载能力，但需加权限和审计。
- 增加文件搜索能力，限制搜索根目录和最大扫描规模。
- 增加日志文件 tail 模式。
- 增加语法高亮。
- 增加图片和 Markdown 预览。
- 增加多服务器/多根目录切换。
