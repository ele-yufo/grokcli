# grokcli

**English** · [中文](README.zh-CN.md)

**Your SuperGrok / X Premium+ subscription, as a terminal Swiss-army knife for Grok — chat, search, images, video, speech. No API key. No dependencies.**

![python](https://img.shields.io/badge/python-3.9%2B-blue) ![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen) ![license](https://img.shields.io/badge/license-MIT-green)

`grokcli` logs in with your **SuperGrok** or **X Premium+** subscription via browser OAuth and talks to the xAI API directly — so a single login unlocks every Grok modality from the command line. It is written in **pure Python standard library**: no `pip` packages to install, nothing to compile. It is built, first and foremost, to be driven by AI agents.

## 🤖 Install with your agent (recommended)

This CLI is made for agents, so the easiest way to install it is to let one do it.
**Copy the prompt below and paste it into Claude Code (or Cursor, Codex, or any coding agent).** The agent fetches the page, installs, and verifies — you do nothing else.

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

Once installed, the agent already knows everything: `grokcli help` prints the complete,
self-contained manual in a single command, and every `grokcli <command> --help` is atomic
(prerequisites, flags, examples, output format, exit codes) — no external docs required.

## Manual install

If you'd rather install it yourself, pick whichever you have — all put a `grokcli` command on your `PATH`:

```bash
uv tool install git+https://github.com/ele-yufo/grokcli      # recommended (isolated, fast)
pipx install     git+https://github.com/ele-yufo/grokcli      # or pipx
pip install      git+https://github.com/ele-yufo/grokcli      # or pip (use a virtualenv)
```

<details>
<summary>From a local clone</summary>

```bash
git clone https://github.com/ele-yufo/grokcli && cd grokcli
pip install .          # or:  make install   /   uv tool install .
```
</details>

Then sign in once and verify:

```bash
grokcli login          # opens your browser; headless? add --manual-paste
grokcli doctor         # checks auth, connectivity, and entitlement
```

> Requires Python 3.9+ and an active **SuperGrok** or **X Premium+** subscription.

## In action

```console
$ grokcli chat "Explain entropy in one sentence"
Entropy measures how many microscopic arrangements match a system's macroscopic
state — in short, nature's tendency toward disorder.

$ grokcli image "a red origami fox" -a 16:9
./grokcli-output/20260603_..._a_red_origami_fox.png
```

## Why grokcli

- 🔑 **No API key.** Authenticates with your existing SuperGrok / X Premium+ subscription (OAuth 2.0 PKCE) — you don't pay per token.
- 📦 **Zero dependencies.** Pure Python 3.9+ stdlib. Runs anywhere Python does; no `node_modules`, no Rust toolchain, no third-party `pip` packages.
- 🎛️ **Every modality, one tool.** Chat, X + web search, image generation & editing, text/image/reference-to-video, video extension, TTS, and transcription — all as scriptable commands.
- 🤖 **Agent-native.** Stable exit codes, JSON output mode, and a fully self-contained help system (`grokcli help` = the whole manual in one call).
- 🧵 **Resumable chats.** Conversations persist locally (bounded) and continue across runs with `-c`.

## How it compares

`grokcli` occupies one niche on purpose: a **zero-dependency, subscription-auth Grok
*capability* CLI** — not a coding agent. The honest landscape (stars ≈ 2026-06):

| | **grokcli** | Moore grok-cli | superagent grok-cli | official Grok Build |
|---|:---:|:---:|:---:|:---:|
| Stars | new | ~40 | ~3.1k | closed-source |
| Install | Python · **zero deps** | Rust binary | TypeScript · npm | bundled binary |
| Auth | **subscription OAuth — no key** | subscription OAuth | API key | subscription (Heavy) |
| Chat · search | ✅ · ✅ | ✅ · ✅ | ✅ · ✅ | ✅ · — |
| Image (gen · edit) | ✅ · ✅ | ✅ · ✅ | as a tool | — |
| Video | ✅ T2V/I2V/R2V/extend | ✅ T2V/I2V/edit/extend | as a tool | — |
| TTS · ASR | ✅ · ✅ | ✅ · ✅ | — | — |
| Resumable sessions | ✅ | — | ✅ | ✅ |
| Coding agent | — | — | ✅ | ✅ |

**Being honest:** the popular tools (superagent, the official Grok Build) are *coding agents* —
that's where the stars are, and grokcli doesn't compete there by design. Moore's Rust CLI is the
closest peer; grokcli's edges over it are zero-dependency portability (runs anywhere Python does),
resumable sessions, reference-to-video, a built-in `doctor`, and agent-native self-documenting help.

## Commands

```text
grokcli login [--no-browser] [--manual-paste] [--from-official]   sign in (OAuth, no API key)
grokcli logout                                                    remove stored credentials
grokcli status                                                    login status & token expiry
grokcli doctor [--offline]                                        health check

grokcli chat [PROMPT] [-m MODEL] [-s SYSTEM] [--no-stream] [--web] [--x]
             [-c] [--session NAME] [--new]                        one-shot, stdin ('-'), or a REPL; resumable
grokcli search QUERY [--no-web] [--no-x]                          X + web search, answered with citations
grokcli sessions list | show [id] | clear [id|--all]              manage saved conversations
grokcli models                                                    list available models

grokcli image PROMPT [-a ASPECT] [-r 1k|2k] [-n N]                generate image(s)
grokcli image-edit PROMPT -i SRC [-i SRC2 -i SRC3] [-a ASPECT]    edit 1-3 source images by prompt
grokcli video PROMPT [-i IMG] [--ref IMG ...] [-r 480p|720p|1080p] [-d 1-15]
                                                                  text- / image- / reference-to-video
grokcli video-extend VIDEO [PROMPT] [-d SECONDS]                  extend an existing video
grokcli tts TEXT [--voice V] [--language en] [-f mp3]             text-to-speech
grokcli voices                                                    list TTS voices
grokcli transcribe AUDIO                                          speech-to-text (ASR)

grokcli config show | path | get KEY | set KEY VALUE              view/change saved defaults
grokcli help [command]                                            the complete manual, in one call
```

Run `grokcli <command> --help` for details and examples on any command.

### Video modes

| Mode | Flag | Model used |
|------|------|------------|
| Text-to-video (T2V) | *(none)* | `grok-imagine-video` |
| Image-to-video (I2V) | `-i IMAGE` | `grok-imagine-video-1.5-preview` |
| Reference-to-video (R2V) | `--ref IMG` (up to 7) | `grok-imagine-video` |

Duration is validated per model (1–15s); `1080p` exists but is subscription-tier-gated.

## Output & scripting

Results go to **stdout**; progress, spinners, and errors go to **stderr**. Output auto-detects **text** on a terminal and **JSON** when piped or redirected (force with `--output text|json`).

```bash
grokcli chat "name 3 primary colors" --no-stream --output json | jq -r .text
```

Exit codes: `0` ok · `2` usage · `3` auth · `4` quota · `5` timeout · `6` network · `10` content filtered · `130` interrupted.

## Configuration

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
grokcli config set chat_model grok-4.3
grokcli config set output_dir ~/Pictures/grok
```

Generated media is written to `./grokcli-output/` (under the current working
directory). Saved chat sessions live in
`~/.config/grokcli/sessions/` and are bounded automatically (tune with
`GROKCLI_MAX_SESSION_MESSAGES` and `GROKCLI_MAX_SESSIONS`).

## How it works

`grokcli login` runs an OAuth 2.0 PKCE flow against `accounts.x.ai`, stores the tokens
in `~/.config/grokcli/auth.json` (mode `600`), and refreshes them automatically. It is
**independent** of the official Grok CLI — it never touches `~/.grok/` (except the
optional one-time `grokcli login --from-official` import). The OAuth bearer is pinned so
it is only ever sent to `*.x.ai`.

## Development

```bash
make test     # stdlib unittest suite; no test dependencies
```

Tests live next to the modules they cover (`grokcli/**/test_*.py`).

## License

[MIT](LICENSE)
