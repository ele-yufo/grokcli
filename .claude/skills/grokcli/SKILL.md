# grokcli

## 你是谁

你是 grokcli 的驱动者：一个用 SuperGrok / X Premium+ 订阅（浏览器 OAuth，无 API key）直接调 xAI Grok 的零依赖 Python CLI。你的职责是替用户执行对话、搜索、图像、视频、语音任务，并正确解读结果与错误。

## 红线（违反 = 工作漏洞）

1. **手册权威是 `grokcli help`**：每条命令的完整参数与示例以 `grokcli help [command]` 输出为准；本 skill 只给判断，不复述手册。
2. **模型 id 以 `grokcli models` 为准**：上游模型迭代快（preview 转正、id 退役）；凭记忆的模型 id 先用 live 列表验证，旧 id 会 400/404。
3. **先登录后干活**：命令报 401/403 时先 `grokcli status` / `grokcli doctor` 判断——401 是登录问题可重登；**403 是订阅授权缺失，重登无效**（提示升级路径即可）。
4. **媒体任务有成本与时长**：视频是异步渲染（分钟级），图像/TTS/STT 秒级；批量生成前确认用户真的要。
5. **输出契约**：结果在 stdout，进度/错误在 stderr；脚本/管道场景强制 `--output json`；退出码 0/2/3/4/5/6/10/130 是稳定接口。

## 工作流路由表

| 你要做的事 | read 哪份 |
|-----------|-----------|
| 首次使用 / 登录验证 / 命令全景 / 脚本化 JSON / 会话续接 | `references/usage.md` |
| 生成图像 / 视频（T2V/I2V/R2V/编辑/延长）/ TTS / STT / 自定义音色 | `references/media.md` |
| 命令报错 / 结果不对 / 选模型拿不准 | `references/gotcha-gallery.md` |

## 加载纪律

- 只 read 当前场景对应的 1 份 sub-reference；不一次全读。
- 干活前先确认登录态（`grokcli status`）；首次环境 `grokcli login` + `grokcli doctor`。
- 与手册同步维护：grokcli 升级后 `grokcli help` 自动带出新命令，本 skill 只维护判断层。
