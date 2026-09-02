# 使用手册（判断层）

权威参数与示例一律以 `grokcli help` / `grokcli help <command>` 输出为准。这里只给判断。

## 登录与验证

```bash
grokcli login            # 浏览器 OAuth；无浏览器/SSH 用 --manual-paste
grokcli status           # 登录态 + token 过期时间
grokcli doctor           # 健康检查：凭证、网络、订阅授权（--offline 跳过网络）
```

- 403 与登录无关：提示"订阅 tier 缺 API 权限，升级见 https://x.ai/grok"。
- 凭证在 `~/.config/grokcli/auth.json`（0600），独立于官方 `~/.grok`。

## 命令全景（速查）

| 类别 | 命令 |
|------|------|
| 对话 | `chat`（一次性 / stdin `-` / REPL；`-c` 续接、`--session NAME`、`--effort`、`--priority`、`--web`/`--x` 搜索） |
| 搜索 | `search`（X + web 双源，默认开） |
| 会话 | `sessions list/show/clear` |
| 图像 | `image`（生成）、`image-edit`（1-3 张源图按提示编辑） |
| 视频 | `video`（T2V/I2V/R2V）、`video-extend`（延长）、`video-edit`（编辑） |
| 语音 | `tts`、`voices`（内置音色）、`voice`（克隆/管理自定义音色）、`transcribe` |
| 系统 | `models`、`quota`、`config`、`help`、`status`、`doctor`、`login`、`logout` |

## 脚本化契约

- 结果 → stdout；spinner/进度/引用/错误 → stderr。
- 管道或重定向时自动 JSON；脚本里显式 `--output json` 更稳。
- 退出码：`0` 成功 · `2` 用法 · `3` 登录 · `4` 配额 · `5` 超时 · `6` 网络 · `10` 内容被过滤 · `130` 中断。
- JSON 输出形状：`chat` → `{"text","citations","usage","session"}`；媒体 → `{"path"|"paths"}`；`transcribe` → `{"text"}`。

```bash
grokcli chat "name 3 colors" --no-stream --output json | jq -r .text
```

## 对话与搜索

- 默认模型 `grok-4.6`（旗舰，500k ctx）；`--effort low|medium|high` 调推理强度（4.6 拒绝 `none`，400）。旧 id（4.5/4.3 等）上游仍在，`-m` 直接指定即可。
- 续接会话：`grokcli chat -c "继续"`（本地持久化，消息数/会话数有界）。
- `search` 答案带内联引用 `[[1]](url)`；引用来源在 stderr 的 Sources 块。

## 错误解读

- 400：请求形状/参数问题（对照 `grokcli help <cmd>` 与模型能力）。
- 401：token 失效，自动刷新后重试一次；仍 401 则重登。
- 403：订阅授权缺失（功能级：如 R2V 配音、自定义音色、1080p 配额）。
- 404：模型 id 不存在或已退役 → `grokcli models` 看 live 列表。
- 429/4：配额/限流，稍后重试；剩余量与重置时间用 `grokcli quota` 查（周配额百分比 + 分产品用量）。
- 网络类（6）：`--verbose` 看请求详情；检查代理（`HTTPS_PROXY`）。
