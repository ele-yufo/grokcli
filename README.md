# grokcli

**English** · [中文](README.zh-CN.md)

**Your SuperGrok / X Premium+ subscription, as a terminal Swiss-army knife for Grok — chat, search, images, video, speech. No API key. No dependencies.**

![python](https://img.shields.io/badge/python-3.9%2B-blue) ![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen) ![license](https://img.shields.io/badge/license-MIT-green)

`grokcli` logs in with your **SuperGrok** or **X Premium+** subscription via browser OAuth and talks to the xAI API directly — so a single login unlocks every Grok modality from the command line. It is written in **pure Python standard library**: no `pip` packages to install, nothing to compile.

```console
$ grokcli login                     # one-time browser sign-in (no API key)
$ grokcli chat "Explain entropy in one sentence"
Entropy is the measure of how many microscopic arrangements correspond to a system's
macroscopic state — in short, nature's tendency toward disorder.
$ grokcli image "a red origami fox" -a 16:9
~/grokcli-output/20260603_..._a_red_origami_fox.png
```

## Why grokcli

- 🔑 **No API key.** Authenticates with your existing SuperGrok / X Premium+ subscription (OAuth 2.0 PKCE) — you don't pay per token.
- 📦 **Zero dependencies.** Pure Python 3.9+ stdlib. Runs anywhere Python does; no `node_modules`, no Rust toolchain, no `pip install` of third-party packages.
- 🎛️ **Every modality, one tool.** Chat, X + web search, image generation & editing, text/image/reference-to-video, video extension, TTS, and transcription — all as scriptable commands.
- 🤖 **Agent-friendly.** Stable exit codes, JSON output mode, and a fully self-contained help system: `grokcli help` prints the entire manual in one call, so an automated agent can learn the tool with no external docs.
- 🧵 **Resumable chats.** Conversations persist locally (bounded) and continue across runs with `-c`.

## Install

Pick whichever you have. All of them put a `grokcli` command on your `PATH`.

```bash
# Recommended — isolated, modern, fast:
uv tool install git+https://github.com/ele-yufo/grokcli

# Or with pipx:
pipx install git+https://github.com/ele-yufo/grokcli

# Or plain pip (consider a virtualenv):
pip install git+https://github.com/ele-yufo/grokcli
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

## For AI agents

To install and master this CLI **autonomously, with no prior context**, run:

```bash
uv tool install git+https://github.com/ele-yufo/grokcli   # or: pipx install git+https://github.com/ele-yufo/grokcli
grokcli help                                              # prints the ENTIRE manual in one call
grokcli login --manual-paste                              # OAuth; paste the callback URL back (headless-safe)
grokcli doctor                                            # confirm everything works
```

`grokcli help` (and every command's `--help`) is **atomic and self-contained** — it documents the auth prerequisite, all commands, flags, examples, output format, and exit codes. Read it and you know the whole tool; no other documentation is needed.

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

Generated media is written to `~/grokcli-output/`. Saved chat sessions live in
`~/.config/grokcli/sessions/` and are bounded automatically (most-recent messages
per session and most-recent sessions overall; tune with `GROKCLI_MAX_SESSION_MESSAGES`
and `GROKCLI_MAX_SESSIONS`).

## How it works

`grokcli login` runs an OAuth 2.0 PKCE flow against `accounts.x.ai`, stores the tokens
in `~/.config/grokcli/auth.json` (mode `600`), and refreshes them automatically. It is
**independent** of the official Grok CLI — it never touches `~/.grok/` (except the
optional one-time `grokcli login --from-official` import). The OAuth bearer is pinned so
it is only ever sent to `*.x.ai`.

## Development

```bash
make test     # 302 stdlib unittest cases; no test dependencies
```

Tests live next to the modules they cover (`grokcli/**/test_*.py`).

## License

[MIT](LICENSE)
