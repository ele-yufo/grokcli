# grokcli

A standalone command-line client for **xAI Grok**, authenticated with your
**SuperGrok** or **X Premium+** subscription via browser OAuth — no API key
required. It depends only on the Python standard library (zero `pip` packages).

> Status: feature-complete, unit-tested (zero type errors), and **verified
> end-to-end against xAI's live API** — OAuth login, doctor, models, chat
> (streaming + one-shot), search, image, TTS, and transcription all confirmed
> working with a real SuperGrok subscription. Video uses the same submit/poll/
> download pattern as image. TTS/STT REST shapes were discovered live (TTS body
> is `{model, text, voice, language, response_format}`).

## Why

xAI exposes an OAuth 2.0 (PKCE) flow so third-party tools can use a SuperGrok /
X Premium+ subscription. `grokcli` implements that flow itself and talks to the
xAI REST API directly, so a single `grokcli login` unlocks chat and media
generation from the terminal.

It is **independent**: it stores its own credentials under `~/.config/grokcli/`
and never touches the official Grok CLI's `~/.grok/` directory.

## Requirements

- Python 3.9+
- A SuperGrok or X Premium+ subscription
- A browser on the local machine (or use the `--manual-paste` / `--no-browser`
  flows for headless/remote sessions)

## Install

```bash
make install          # pip install .
# or, for development:
make dev-install      # pip install -e .
```

This puts a `grokcli` executable on your `PATH`.

## Commands

```text
grokcli login [--no-browser] [--manual-paste] [--from-official]
                                  authenticate via browser OAuth (PKCE)
grokcli logout                    remove stored credentials
grokcli status                    show login status and token expiry
grokcli doctor [--offline]        diagnose auth, connectivity, entitlement

grokcli chat [PROMPT] [-m MODEL] [-s SYSTEM] [--no-stream] [--web] [--x]
             [-c|--continue] [--session NAME] [--new]
                                  one-shot chat; omit PROMPT for a REPL, '-' for stdin
                                  -c continues the last conversation; --session NAME
                                  keeps a named one; both persist locally and resume
grokcli sessions list | show [id] | clear [id] [--all]
                                  manage saved conversations (~/.config/grokcli/sessions)
grokcli search QUERY [--no-web] [--no-x]
                                  search X + web and summarize with citations
grokcli models                    list available models (GET /v1/models)

grokcli image PROMPT [-a ASPECT] [-r 1k|2k] [-n N] [-m MODEL]
grokcli image-edit PROMPT -i SRC [-i SRC2 -i SRC3] [-a ASPECT] [-r 1k|2k] [-n N]
                                  edit 1-3 source images guided by a prompt
grokcli video PROMPT [-i IMAGE] [--ref IMG ...] [-a ASPECT] [-r 480p|720p] [-d SECONDS]
                                  -i = image-to-video; --ref = reference-to-video (R2V, up to 7)
grokcli video-extend VIDEO [PROMPT] [-d SECONDS]
                                  extend an existing video (local file or URL)
grokcli tts TEXT [--voice V] [--language en] [-f mp3] [-m MODEL]
grokcli voices                    list TTS voices (Ara, Eve, Leo, Rex, ...)
grokcli transcribe AUDIO [-m MODEL]

grokcli config show | path | get KEY | set KEY VALUE
grokcli help [command]            print the complete manual (every command at once)
```

Every command's `--help` is self-contained (description + flags + examples), and
`grokcli help` prints the entire manual in one call — so an automated agent can
learn the whole tool with no prior context and without any external documentation.

Global options accepted after any subcommand: `--output {text,json}`,
`--no-color`, `--verbose`, `--base-url`, `--timeout`, `--proxy`. Output is
auto-detected as JSON when piped, text on a terminal.

Generated images/videos/audio are written to `~/grokcli-output/` by default
(override with `GROKCLI_OUTPUT_DIR` or `config set output_dir`).

Saved chat sessions are bounded so they can't grow without limit: each session
keeps only its most recent messages (`GROKCLI_MAX_SESSION_MESSAGES`, default 100,
which also caps per-request payload) and the store keeps only the most recent
sessions (`GROKCLI_MAX_SESSIONS`, default 50, oldest pruned first). Persistence
is write-on-turn — there is no background polling.

### Relationship to other Grok tools

`grokcli` is self-contained. It is **not** related to the official `grok` CLI
(which lives in `~/.grok/`) and never reads or writes that directory — except
the optional one-time `grokcli login --from-official`, which copies an existing
login out of `~/.grok/auth.json`. (Heads up: the two then share a refresh token,
and whichever refreshes first may rotate it.)

## Development

```bash
make test             # run the stdlib unittest suite
```

Tests live next to the modules they cover (`grokcli/test_*.py`) and use only the
standard library, so no test dependencies are required.

## Configuration

Resolution precedence for every setting is **CLI flag > environment variable >
`~/.config/grokcli/config.json` > built-in default**.

| Setting | Env var | Default |
|---|---|---|
| Config/credential home | `GROKCLI_HOME` | `~/.config/grokcli` |
| API base URL (pinned to `*.x.ai`) | `GROKCLI_BASE_URL` / `XAI_BASE_URL` | `https://api.x.ai/v1` |
| Output format (`text`/`json`) | `GROKCLI_OUTPUT` | auto (json when piped) |
| Request timeout (seconds) | `GROKCLI_TIMEOUT` | `300` |
| Proxy | `HTTPS_PROXY` / `ALL_PROXY` | none |
| Disable color | `NO_COLOR` / `GROKCLI_NO_COLOR` | color on a TTY |

## License

MIT
