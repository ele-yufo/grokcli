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
  <b>Everything Grok. In your terminal. Zero dependencies.</b><br>
  One login with your SuperGrok or X Premium+ subscription unlocks the full xAI stack —<br>
  chat · web & X search · images · video · voice. No API key. No pip installs. Just Python's stdlib.
</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a> ·
  <a href="https://docs.x.ai">xAI API docs</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#command-reference">Command reference</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT license">
  <img src="https://img.shields.io/badge/tests-351%20passing-8A2BE2" alt="351 tests passing">
</p>

---

## ✨ Why you'll love it

| | |
|---|---|
| 🔑 **Your subscription *is* the key** | Browser OAuth (PKCE) with your SuperGrok / X Premium+ account. No API keys, no per-token billing — your subscription just works. |
| 📦 **Zero dependencies, forever** | Pure Python 3.9+ standard library. Runs anywhere Python runs: no `node_modules`, no Rust toolchain, no third-party packages. |
| 🎛️ **Every Grok modality, one command** | Chat & reasoning, X + web search with citations, image generation & editing, text/image/reference-to-video, video editing & extension, TTS, speech-to-text, custom voices. |
| 🤖 **Built for agents** | Stable exit codes, `--output json`, and a fully self-contained manual — `grokcli help` prints the entire documentation in a single call. |
| 🧵 **Conversations that continue** | Sessions persist locally (bounded), resume across invocations with `-c`, and never leak to the cloud. |

## 🤖 Install with your agent (recommended)

grokcli is *made* for agents — so the fastest way to install it is to let one do it.
**Copy this prompt into Claude Code (or Cursor, Codex, any coding agent):**

```text
Install the "grokcli" command-line tool for me. It is a zero-dependency CLI for xAI's
Grok that authenticates with my SuperGrok / X Premium+ subscription (no API key).

1. Fetch and read https://raw.githubusercontent.com/ele-yufo/grokcli/main/README.md
   for full context.
2. Install it (prefer uv; fall back as needed):
       uv tool install git+https://github.com/ele-yufo/grokcli
       # or: pipx install git+https://github.com/ele-yufo/grokcli
       # or: pip  install git+https://github.com/ele-yufo/grokcli
3. Verify: run `grokcli --version`, then `grokcli help` (it prints the entire manual
   in one call — read it so you know every command).
4. Then walk me through `grokcli login` to connect my account, and run `grokcli doctor`
   to confirm it works.
```

Once installed, the agent already knows everything: `grokcli help` is the complete,
self-contained manual, and every `grokcli <command> --help` is atomic — prerequisites,
flags, examples, output format, exit codes. No external docs required.

### Manual install

```bash
uv tool install git+https://github.com/ele-yufo/grokcli      # recommended (isolated, fast)
pipx install     git+https://github.com/ele-yufo/grokcli      # or pipx
pip install      git+https://github.com/ele-yufo/grokcli      # or pip (use a virtualenv)
```

Then sign in once and verify:

```bash
grokcli login          # opens your browser; headless? add --manual-paste
grokcli doctor         # checks auth, connectivity, and entitlement
```

> Requires Python 3.9+ and an active **SuperGrok** or **X Premium+** subscription.

## 🚀 Quickstart

```console
$ grokcli chat "Explain entropy in one sentence"
Entropy measures how many microscopic arrangements match a system's macroscopic
state — in short, nature's tendency toward disorder.

$ grokcli image "a red origami fox" -a 16:9
./grokcli-output/20260806_..._a_red_origami_fox.png

$ grokcli video "a calm ocean wave at sunset" -d 6 -r 1080p
./grokcli-output/20260806_..._a_calm_ocean_wave_at_sunset.mp4

$ grokcli tts "Hello from Grok" --voice eve
./grokcli-output/20260806_..._hello_from_grok.mp3
```

## ⚡ Agent-ready by design

Results go to **stdout**; progress, spinners, and errors go to **stderr**.
Output auto-detects **text** on a terminal and **JSON** when piped — force with `--output text|json`.

```bash
grokcli chat "name 3 primary colors" --no-stream --output json | jq -r .text

# machine-checkable, always:
echo $?   # 0 ok · 2 usage · 3 auth · 4 quota · 5 timeout · 6 network · 10 content filtered · 130 interrupted
```

## 📖 Command reference

```text
grokcli login [--no-browser] [--manual-paste] [--from-official]   sign in (OAuth, no API key)
grokcli logout                                                    remove stored credentials
grokcli status                                                    login status & token expiry
grokcli doctor [--offline]                                        health check

grokcli chat [PROMPT] [-m MODEL] [-s SYSTEM] [--no-stream] [--web] [--x]
             [--effort none|low|medium|high] [--priority] [-c] [--session NAME] [--new]
                                                                  one-shot, stdin ('-'), or a REPL; resumable
grokcli search QUERY [--no-web] [--no-x]                          X + web search, answered with citations
grokcli sessions list | show [id] | clear [id|--all]              manage saved conversations
grokcli models                                                    list available models

grokcli image PROMPT [-a ASPECT] [-r 1k|2k] [-n N]                generate image(s)
grokcli image-edit PROMPT -i SRC [-i SRC2 -i SRC3] [-a ASPECT]    edit 1-3 source images by prompt
grokcli video PROMPT [-i IMG] [--ref IMG ...] [--ref-audio VOICE ...]
             [-r 480p|720p|1080p] [-d 1-15]                       text- / image- / reference-to-video
grokcli video-extend VIDEO [PROMPT] [-d SECONDS]                  extend an existing video
grokcli video-edit VIDEO PROMPT                                   edit an existing video
grokcli tts TEXT [--voice V] [--language en] [-f mp3] [--speed 0.7-1.5]
             [--latency 0|1|2] [--normalize]                      text-to-speech
grokcli voices                                                    list TTS voices
grokcli voice clone AUDIO [--name N] [--gender g] ...             clone a custom voice
grokcli voice list | delete <voice_id>                            manage cloned voices
grokcli transcribe AUDIO [--vad-threshold 0-1] [--diarize] [--keyterm K ...]
                                                                  speech-to-text (ASR)

grokcli config show | path | get KEY | set KEY VALUE              view/change saved defaults
grokcli help [command]                                            the complete manual, in one call
```

Run `grokcli <command> --help` for details and examples on any command.

### 🎨 Image models

`grok-imagine-image-2.0` is the default for both `image` and `image-edit` —
the Imagine Image 2.0 model: sharp typography, strong prompt adherence, and
multi-reference editing (tag sources in the prompt as `<IMAGE_0>`, `<IMAGE_1>`,
`<IMAGE_2>`). The older tiers remain one `-m` away: `grok-imagine-image-quality`
(slower, higher fidelity) and `grok-imagine-image` (fast). Generation and edits
accept up to 10 images per request and wide/phone aspect ratios — `9:19.5`,
`19.5:9`, `9:20`, `20:9`, `1:2`, `2:1`, plus `auto`.

### 🎬 Video modes

| Mode | Flag | Model used |
|------|------|------------|
| Text-to-video (T2V) | *(none)* | `grok-imagine-video-1.5` (default) |
| Image-to-video (I2V) | `-i IMAGE` | `grok-imagine-video-1.5` |
| Reference-to-video (R2V) | `--ref IMG` (up to 7) | `grok-imagine-video-1.5` |
| R2V narration | `--ref-audio VOICE` (up to 3) | `grok-imagine-video-1.5` (tag voices as `<AUDIO_0>` in the prompt) |

`grok-imagine-video-1.5` is the unified model: T2V/I2V/R2V in one, with native
**1080p** (T2V/I2V; R2V capped at 720p). Generation duration is 1–15s;
`video-extend` segments are 2–10s; `video-edit` keeps the input's length.
`-i` (I2V) and `--ref`/`--ref-audio` (R2V) are mutually exclusive.

## ⚙️ Configuration

Resolution order for every setting: **CLI flag > environment variable > `~/.config/grokcli/config.json` > default**.

| Setting | Env var | Default |
|---|---|---|
| Config / credential home | `GROKCLI_HOME` | `~/.config/grokcli` |
| API base URL (pinned to `*.x.ai`) | `GROKCLI_BASE_URL` / `XAI_BASE_URL` | `https://api.x.ai/v1` |
| Output format | `GROKCLI_OUTPUT` | auto (JSON when piped) |
| Request timeout (s) | `GROKCLI_TIMEOUT` | `300` |
| Proxy | `HTTPS_PROXY` / `ALL_PROXY` | none |
| Disable color | `NO_COLOR` | color on a TTY |

```bash
grokcli config set chat_model grok-4.5
grokcli config set output_dir ~/Pictures/grok
```

Generated media is written to `./grokcli-output/` (under the current working
directory). Saved chat sessions live in `~/.config/grokcli/sessions/` and are
bounded automatically (tune with `GROKCLI_MAX_SESSION_MESSAGES` and
`GROKCLI_MAX_SESSIONS`).

## 🧠 How it works

`grokcli login` runs an OAuth 2.0 PKCE flow against `accounts.x.ai`, stores the
tokens in `~/.config/grokcli/auth.json` (mode `600`), and refreshes them
automatically. It is **independent** of the official Grok CLI — it never touches
`~/.grok/` (except the optional one-time `grokcli login --from-official`
import). The OAuth bearer is pinned so it is only ever sent to `*.x.ai`.

## 🛠 Development

```bash
make test     # stdlib unittest suite; no test dependencies
```

Tests live next to the modules they cover (`grokcli/**/test_*.py`).

## 📄 License

[MIT](LICENSE)
