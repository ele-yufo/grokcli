# grokcli

[English](README.md) · **中文**

**把你的 SuperGrok / X Premium+ 订阅,变成终端里的 Grok 瑞士军刀 —— 对话、搜索、图片、视频、语音。无需 API key,零依赖。**

![python](https://img.shields.io/badge/python-3.9%2B-blue) ![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen) ![license](https://img.shields.io/badge/license-MIT-green)

`grokcli` 通过浏览器 OAuth 用你的 **SuperGrok** 或 **X Premium+** 订阅登录,直连 xAI API —— 一次登录即可在命令行使用 Grok 的全部能力。它用**纯 Python 标准库**编写:不装任何 `pip` 包,不用编译。它首要的设计目标,就是被 AI Agent 驱动。

## 🤖 让你的 Agent 来装(推荐)

这个 CLI 是为 Agent 准备的,所以最省事的安装方式就是交给 Agent。
**复制下面这段 prompt,粘贴到 Claude Code(或 Cursor、Codex 等任意编码 Agent)里。** Agent 会自己抓取页面、安装并验证 —— 你什么都不用做。

```text
帮我安装 "grokcli" 命令行工具。它是一个零依赖的 xAI Grok CLI,用我的
SuperGrok / X Premium+ 订阅登录(不需要 API key)。

1. 抓取并阅读 https://raw.githubusercontent.com/ele-yufo/grokcli/main/README.md
   获取完整说明。
2. 安装(优先用 uv,不行再退而求其次):
       uv tool install git+https://github.com/ele-yufo/grokcli
       # 或: pipx install git+https://github.com/ele-yufo/grokcli
       # 或: pip  install git+https://github.com/ele-yufo/grokcli
3. 验证:运行 `grokcli --version`,再运行 `grokcli help`(它一条命令打印完整手册
   —— 读一遍你就知道所有命令了)。
4. 然后带我走一遍 `grokcli login` 连接我的账号,并运行 `grokcli doctor` 确认可用。
```

装好后 Agent 就全懂了:`grokcli help` 一条命令打印**完整、自包含**的手册,每个
`grokcli <命令> --help` 也都是原子化的(前置条件、参数、示例、输出格式、退出码)——
不需要任何外部文档。

## 手动安装

如果你想自己装,任选一种(都会把 `grokcli` 装到 `PATH` 上):

```bash
uv tool install git+https://github.com/ele-yufo/grokcli      # 推荐(隔离、快)
pipx install     git+https://github.com/ele-yufo/grokcli      # 或 pipx
pip install      git+https://github.com/ele-yufo/grokcli      # 或 pip(建议在 virtualenv 中)
```

<details>
<summary>从本地克隆安装</summary>

```bash
git clone https://github.com/ele-yufo/grokcli && cd grokcli
pip install .          # 或:  make install   /   uv tool install .
```
</details>

然后登录一次并验证:

```bash
grokcli login          # 打开浏览器;无图形界面的机器加 --manual-paste
grokcli doctor         # 检查认证、连通性与订阅权限
```

> 需要 Python 3.9+ 和有效的 **SuperGrok** 或 **X Premium+** 订阅。

## 实际效果

```console
$ grokcli chat "用一句话解释熵"
熵衡量一个系统的宏观状态对应多少种微观排列方式 —— 简单说,就是自然走向无序的倾向。

$ grokcli image "一只红色的折纸狐狸" -a 16:9
~/grokcli-output/20260603_..._a_red_origami_fox.png
```

## 为什么用 grokcli

- 🔑 **不需要 API key。** 用你已有的 SuperGrok / X Premium+ 订阅登录(OAuth 2.0 PKCE),不按 token 付费。
- 📦 **零依赖。** 纯 Python 3.9+ 标准库。有 Python 的地方就能跑;不要 `node_modules`、不要 Rust 工具链、不装任何第三方 `pip` 包。
- 🎛️ **一个工具,所有模态。** 对话、X + 网页搜索、图片生成与编辑、文/图/参考生成视频、视频延长、TTS、语音转写 —— 全是可脚本化的命令。
- 🤖 **原生为 Agent 设计。** 稳定退出码、JSON 输出模式,以及完全自包含的帮助系统(`grokcli help` = 一条命令出完整手册)。
- 🧵 **可续接对话。** 会话本地持久化(有上限),用 `-c` 跨次续接。

## 命令

```text
grokcli login [--no-browser] [--manual-paste] [--from-official]   登录(OAuth,无需 API key)
grokcli logout                                                    删除已存凭证
grokcli status                                                    登录状态与 token 过期时间
grokcli doctor [--offline]                                        健康检查

grokcli chat [PROMPT] [-m MODEL] [-s SYSTEM] [--no-stream] [--web] [--x]
             [-c] [--session NAME] [--new]                        一次性 / stdin('-')/ REPL;可续接
grokcli search QUERY [--no-web] [--no-x]                          X + 网页搜索,带引用作答
grokcli sessions list | show [id] | clear [id|--all]              管理已存对话
grokcli models                                                    列出可用模型

grokcli image PROMPT [-a ASPECT] [-r 1k|2k] [-n N]                生成图片
grokcli image-edit PROMPT -i SRC [-i SRC2 -i SRC3] [-a ASPECT]    按提示编辑 1-3 张源图
grokcli video PROMPT [-i IMG] [--ref IMG ...] [-r 480p|720p|1080p] [-d 1-15]
                                                                  文/图/参考生成视频
grokcli video-extend VIDEO [PROMPT] [-d SECONDS]                  延长已有视频
grokcli tts TEXT [--voice V] [--language en] [-f mp3]             文字转语音
grokcli voices                                                    列出 TTS 音色
grokcli transcribe AUDIO                                          语音转文字(ASR)

grokcli config show | path | get KEY | set KEY VALUE              查看/修改默认配置
grokcli help [command]                                            完整手册,一条命令搞定
```

任何命令加 `--help` 查看详细参数和示例。

### 视频三种模式

| 模式 | 参数 | 使用的模型 |
|------|------|-----------|
| 文生视频 (T2V) | *(无)* | `grok-imagine-video` |
| 图生视频 (I2V) | `-i IMAGE` | `grok-imagine-video-1.5-preview` |
| 参考生成视频 (R2V) | `--ref IMG`(最多 7 张) | `grok-imagine-video` |

时长按模型校验(1–15 秒);`1080p` 存在但受订阅 tier 限制。

## 输出与脚本化

结果输出到 **stdout**;进度、spinner、错误输出到 **stderr**。在终端里默认 **文本**,被管道/重定向时自动切 **JSON**(可用 `--output text|json` 强制)。

```bash
grokcli chat "说出三种三原色" --no-stream --output json | jq -r .text
```

退出码:`0` 成功 · `2` 用法错误 · `3` 认证 · `4` 配额 · `5` 超时 · `6` 网络 · `10` 内容拦截 · `130` 中断。

## 配置

每项设置的优先级:**命令行参数 > 环境变量 > `~/.config/grokcli/config.json` > 默认值**。

| 设置 | 环境变量 | 默认值 |
|---|---|---|
| 配置/凭证目录 | `GROKCLI_HOME` | `~/.config/grokcli` |
| API base URL(锁定 `*.x.ai`) | `GROKCLI_BASE_URL` / `XAI_BASE_URL` | `https://api.x.ai/v1` |
| 输出格式 | `GROKCLI_OUTPUT` | 自动(管道时 JSON) |
| 请求超时(秒) | `GROKCLI_TIMEOUT` | `300` |
| 代理 | `HTTPS_PROXY` / `ALL_PROXY` | 无 |
| 关闭彩色 | `NO_COLOR` | TTY 下彩色 |

```bash
grokcli config set chat_model grok-4.3
grokcli config set output_dir ~/Pictures/grok
```

生成的媒体写入 `~/grokcli-output/`。已存对话位于 `~/.config/grokcli/sessions/`,会自动限制大小
(可用 `GROKCLI_MAX_SESSION_MESSAGES` 和 `GROKCLI_MAX_SESSIONS` 调整)。

## 工作原理

`grokcli login` 对 `accounts.x.ai` 跑一遍 OAuth 2.0 PKCE 流程,把 token 存到
`~/.config/grokcli/auth.json`(权限 `600`),并自动刷新。它与官方 Grok CLI **完全独立**,
绝不碰 `~/.grok/`(除非你显式用一次性的 `grokcli login --from-official` 导入)。OAuth bearer
被锁定,只会发往 `*.x.ai`。

## 开发

```bash
make test     # 标准库 unittest 测试集;无测试依赖
```

测试与被测模块同级(`grokcli/**/test_*.py`)。

## 许可证

[MIT](LICENSE)
