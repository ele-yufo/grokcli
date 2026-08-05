<p align="center">
  <img src="assets/banner.jpg" alt="grokcli" width="100%">
</p>

```text
   ██████╗ ██████╗   ██████╗ ██╗  ██╗  ██████╗ ██╗      ██╗
  ██╔════╝ ██╔══██╗ ██╔═══██╗ ██║ ██╔╝ ██╔════╝ ██║      ██║
  ██║  ███╗ ██████╔╝ ██║   ██║ █████╔╝  ██║      ██║      ██║
  ██║   ██║ ██╔══██╗ ██║   ██║ ██╔═██╗  ██║      ██║      ██║
  ╚██████╔╝ ██║  ██║ ╚██████╔╝ ██║  ██╗ ╚██████╗ ╚██████╗ ╚█║
   ╚═════╝ ╚═╝  ╚═╝  ╚═════╝ ╚═╝  ╚═╝  ╚═════╝  ╚═════╝  ╚╝
```

<p align="center">
  <b>所有 Grok,都在你的终端里。零依赖。</b><br>
  一次登录你的 SuperGrok 或 X Premium+ 订阅,解锁 xAI 全栈能力 ——<br>
  对话 · 网页与 X 搜索 · 图片 · 视频 · 语音。无需 API key,无需 pip 安装,纯 Python 标准库。
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="https://docs.x.ai">xAI API 文档</a> ·
  <a href="#快速上手">快速上手</a> ·
  <a href="#命令参考">命令参考</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen" alt="零依赖">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT 许可证">
  <img src="https://img.shields.io/badge/tests-351%20passing-8A2BE2" alt="351 个测试通过">
</p>

---

## ✨ 为什么你会爱上它

| | |
|---|---|
| 🔑 **你的订阅就是钥匙** | 用 SuperGrok / X Premium+ 账号走浏览器 OAuth(PKCE)。没有 API key,不按 token 计费 —— 订阅在手,一切都有。 |
| 📦 **零依赖,永远** | 纯 Python 3.9+ 标准库。有 Python 的地方就能跑:不要 `node_modules`,不要 Rust 工具链,不装任何第三方包。 |
| 🎛️ **一个命令,所有模态** | 对话与推理、X + 网页搜索(带引用)、图片生成与编辑、文/图/参考生成视频、视频编辑与延长、TTS、语音转写、自定义音色。 |
| 🤖 **为 Agent 而生** | 稳定退出码、`--output json`,以及完全自包含的手册 —— `grokcli help` 一条命令打印全部文档。 |
| 🧵 **对话不会断** | 会话本地持久化(有上限),用 `-c` 跨次续接,数据不离开你的机器。 |

## 🤖 让你的 Agent 来装(推荐)

grokcli 天生就是给 Agent 用的 —— 所以最快的安装方式就是交给 Agent 办。
**复制下面这段 prompt,粘贴到 Claude Code(或 Cursor、Codex 等任意编码 Agent)里:**

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

装好后 Agent 就全懂了:`grokcli help` 就是**完整、自包含**的手册,每个
`grokcli <命令> --help` 也都是原子化的 —— 前置条件、参数、示例、输出格式、退出码,
一应俱全,不需要任何外部文档。

### 手动安装

```bash
uv tool install git+https://github.com/ele-yufo/grokcli      # 推荐(隔离、快)
pipx install     git+https://github.com/ele-yufo/grokcli      # 或 pipx
pip install      git+https://github.com/ele-yufo/grokcli      # 或 pip(建议在 virtualenv 中)
```

然后登录一次并验证:

```bash
grokcli login          # 打开浏览器;无图形界面的机器加 --manual-paste
grokcli doctor         # 检查认证、连通性与订阅权限
```

> 需要 Python 3.9+ 和有效的 **SuperGrok** 或 **X Premium+** 订阅。

## 🚀 快速上手

```console
$ grokcli chat "用一句话解释熵"
熵衡量一个系统的宏观状态对应多少种微观排列方式 —— 简单说,就是自然走向无序的倾向。

$ grokcli image "一只红色的折纸狐狸" -a 16:9
./grokcli-output/20260806_..._a_red_origami_fox.png

$ grokcli video "日落时分平静的海浪" -d 6 -r 1080p
./grokcli-output/20260806_..._a_calm_ocean_wave_at_sunset.mp4

$ grokcli tts "你好,我是 Grok" --voice eve
./grokcli-output/20260806_..._hello_from_grok.mp3
```

## ⚡ 为 Agent 而生的设计

结果输出到 **stdout**;进度、spinner、错误输出到 **stderr**。在终端里默认
**文本**,被管道/重定向时自动切 **JSON**(可用 `--output text|json` 强制)。

```bash
grokcli chat "说出三种三原色" --no-stream --output json | jq -r .text

# 机器可检查,永远如此:
echo $?   # 0 成功 · 2 用法错误 · 3 认证 · 4 配额 · 5 超时 · 6 网络 · 10 内容拦截 · 130 中断
```

## 📖 命令参考

```text
grokcli login [--no-browser] [--manual-paste] [--from-official]   登录(OAuth,无需 API key)
grokcli logout                                                    删除已存凭证
grokcli status                                                    登录状态与 token 过期时间
grokcli doctor [--offline]                                        健康检查

grokcli chat [PROMPT] [-m MODEL] [-s SYSTEM] [--no-stream] [--web] [--x]
             [--effort none|low|medium|high] [--priority] [-c] [--session NAME] [--new]
                                                                  一次性 / stdin('-')/ REPL;可续接
grokcli search QUERY [--no-web] [--no-x]                          X + 网页搜索,带引用作答
grokcli sessions list | show [id] | clear [id|--all]              管理已存对话
grokcli models                                                    列出可用模型

grokcli image PROMPT [-a ASPECT] [-r 1k|2k] [-n N]                生成图片
grokcli image-edit PROMPT -i SRC [-i SRC2 -i SRC3] [-a ASPECT]    按提示编辑 1-3 张源图
grokcli video PROMPT [-i IMG] [--ref IMG ...] [--ref-audio VOICE ...]
             [-r 480p|720p|1080p] [-d 1-15]                       文/图/参考生成视频
grokcli video-extend VIDEO [PROMPT] [-d SECONDS]                  延长已有视频
grokcli video-edit VIDEO PROMPT                                   按提示编辑已有视频
grokcli tts TEXT [--voice V] [--language en] [-f mp3] [--speed 0.7-1.5]
             [--latency 0|1|2] [--normalize]                      文字转语音
grokcli voices                                                    列出 TTS 音色
grokcli voice clone AUDIO [--name N] [--gender g] ...             克隆自定义音色
grokcli voice list | delete <voice_id>                            管理克隆音色
grokcli transcribe AUDIO [--vad-threshold 0-1] [--diarize] [--keyterm K ...]
                                                                  语音转文字(ASR)

grokcli config show | path | get KEY | set KEY VALUE              查看/修改默认配置
grokcli help [command]                                            完整手册,一条命令搞定
```

任何命令加 `--help` 查看详细参数和示例。

### 🎬 视频模式

| 模式 | 参数 | 使用的模型 |
|------|------|-----------|
| 文生视频 (T2V) | *(无)* | `grok-imagine-video-1.5`(默认) |
| 图生视频 (I2V) | `-i IMAGE` | `grok-imagine-video-1.5` |
| 参考生成视频 (R2V) | `--ref IMG`(最多 7 张) | `grok-imagine-video-1.5` |
| R2V 配音 | `--ref-audio VOICE`(最多 3 个) | `grok-imagine-video-1.5`(在提示词中用 `<AUDIO_0>` 等标签指位) |

`grok-imagine-video-1.5` 是统一模型:T2V/I2V/R2V 三合一,原生 **1080p**
(T2V/I2V;R2V 上限 720p)。生成时长 1–15 秒;`video-extend` 追加段为 2–10 秒;
`video-edit` 保持原片长度。`-i`(I2V)与 `--ref`/`--ref-audio`(R2V)互斥。

## ⚙️ 配置

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
grokcli config set chat_model grok-4.5
grokcli config set output_dir ~/Pictures/grok
```

生成的媒体写入 `./grokcli-output/`(当前工作目录下)。已存对话位于
`~/.config/grokcli/sessions/`,会自动限制大小(可用 `GROKCLI_MAX_SESSION_MESSAGES`
和 `GROKCLI_MAX_SESSIONS` 调整)。

## 🧠 工作原理

`grokcli login` 对 `accounts.x.ai` 跑一遍 OAuth 2.0 PKCE 流程,把 token 存到
`~/.config/grokcli/auth.json`(权限 `600`),并自动刷新。它与官方 Grok CLI
**完全独立**,绝不碰 `~/.grok/`(除非你显式用一次性的 `grokcli login --from-official`
导入)。OAuth bearer 被锁定,只会发往 `*.x.ai`。

## 🛠 开发

```bash
make test     # 标准库 unittest 测试集;无测试依赖
```

测试与被测模块同级(`grokcli/**/test_*.py`)。

## 📄 许可证

[MIT](LICENSE)
