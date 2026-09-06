"""grokcli command-line entrypoint: argument parsing, dispatch, error handling.

Global options (``--output``, ``--verbose``, ``--no-color``, ``--base-url``,
``--timeout``, ``--proxy``) are accepted after any subcommand. Every command
resolves a :class:`Settings`, runs, and any :class:`GrokError` is rendered to
stderr and turned into the carried exit code. Results go to stdout.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Mapping, Optional

from . import __version__, config, output
from .errors import ExitCode, GrokError, UsageError


# Help text is written to be ATOMIC: an agent with zero prior context should be
# able to learn the entire tool from `grokcli --help` plus `grokcli <cmd> --help`,
# without any external documentation or skill. Hence the rich descriptions/epilogs.
_RAW = argparse.RawDescriptionHelpFormatter

_MAIN_DESCRIPTION = (
    "grokcli — a standalone command-line client for xAI's Grok, authenticated with a\n"
    "SuperGrok or X Premium+ subscription via browser OAuth (no API key needed).\n"
    "Depends only on the Python standard library."
)

_MAIN_EPILOG = """\
GETTING STARTED (do this first — nothing works until you are logged in):
  1. grokcli login            one-time browser OAuth against accounts.x.ai
                              (headless/SSH/remote: grokcli login --manual-paste)
  2. grokcli doctor           verify auth, connectivity, and entitlement
  3. grokcli chat "hello"     start using it

CAPABILITIES:
  chat        converse with Grok: one-shot, from stdin, or an interactive REPL; resumable
  search      X (Twitter) + web search answered by Grok, with citations
  image       generate images           image-edit  edit existing images
  video       generate videos (T2V/I2V/R2V)    video-edit  edit a video
  video-extend  extend a video          tts         text-to-speech
  voice       clone / list / delete custom voices   transcribe  speech-to-text
  models      list available models     quota       show subscription usage
  voices      list TTS voices           sessions    manage saved chats
  config      view/change saved defaults
  status      show login state          doctor      health check     logout  sign out

OUTPUT CONTRACT (stable for scripting):
  Results go to stdout; progress, spinners, and errors go to stderr.
  Format auto-detects: text on a terminal, JSON when piped/redirected. Force with --output text|json.

EXIT CODES:
  0 success   2 usage error   3 auth (run `grokcli login`)   4 quota/rate-limit
  5 timeout   6 network        10 content filtered            130 interrupted

EXAMPLES:
  grokcli login
  grokcli chat "Explain quantum tunneling in two sentences"
  grokcli chat "Summarize this" < notes.txt          # or:  ... | grokcli chat -
  grokcli chat -c "now give an example"              # continue the previous conversation
  grokcli search "latest xAI announcements"
  grokcli image "a red origami fox" -a 16:9 -r 2k
  grokcli video "a wave breaking on rocks" -d 6
  grokcli tts "Hello there" --voice Rex
  grokcli transcribe recording.mp3
  grokcli chat "in 3 words" --no-stream --output json | jq -r .text

FILES & ENVIRONMENT:
  Credentials  ~/.config/grokcli/auth.json (chmod 600)    Config  ~/.config/grokcli/config.json
  Sessions     ~/.config/grokcli/sessions/                Output  ./grokcli-output/
  GROKCLI_HOME overrides the config dir.   NO_COLOR disables color.   HTTPS_PROXY sets a proxy.

Run `grokcli <command> --help` for the full options and examples of any command,
or `grokcli help` to print the complete manual (every command at once).
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grokcli",
        formatter_class=_RAW,
        description=_MAIN_DESCRIPTION,
        epilog=_MAIN_EPILOG,
    )
    parser.add_argument("--version", action="version", version=f"grokcli {__version__}")
    globals_parent = _global_options_parent()
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    _add_auth_commands(sub, globals_parent)
    _add_doctor_command(sub, globals_parent)
    _add_chat_commands(sub, globals_parent)
    _add_media_commands(sub, globals_parent)
    _add_sessions_command(sub, globals_parent)
    _add_models_command(sub, globals_parent)
    _add_quota_command(sub, globals_parent)
    _add_config_command(sub, globals_parent)
    _add_help_command(sub, globals_parent)
    return parser


def _add_help_command(sub, parent) -> None:
    helpcmd = _sub(
        sub, "help", parent,
        help_text="print the complete manual (every command at once)",
        description=(
            "Print the full grokcli manual: the top-level overview plus the help for every\n"
            "command, in one shot. Designed so an automated agent can learn the entire tool\n"
            "from a single command with no prior context."
        ),
        epilog="EXAMPLES:\n  grokcli help            print everything\n  grokcli help chat       just the chat command",
    )
    helpcmd.add_argument("topic", nargs="?", help="a command name to show help for (default: all)")
    helpcmd.set_defaults(func=_cmd_help)


def _sub(sub, name, parent, *, help_text, description, epilog):
    """Register a subcommand whose own --help is self-contained (examples included)."""
    return sub.add_parser(
        name, parents=[parent], help=help_text, formatter_class=_RAW, description=description, epilog=epilog
    )


def _global_options_parent() -> argparse.ArgumentParser:
    """A parent parser carrying options every subcommand accepts."""
    g = argparse.ArgumentParser(add_help=False)
    g.add_argument("--output", choices=["text", "json"], default=None, help="output format (default: auto)")
    g.add_argument("--no-color", action="store_true", help="disable ANSI color")
    g.add_argument("--verbose", action="store_true", help="log requests to stderr")
    g.add_argument("--base-url", default=None, help="override xAI API base URL (must be on *.x.ai)")
    g.add_argument("--timeout", type=float, default=None, help="request timeout in seconds")
    g.add_argument("--proxy", default=None, help="HTTP(S) proxy URL")
    return g


def _add_auth_commands(sub, parent) -> None:
    login = _sub(
        sub, "login", parent,
        help_text="authenticate via browser OAuth (run this first)",
        description=(
            "Sign in with a SuperGrok or X Premium+ subscription via browser OAuth (PKCE).\n"
            "Tokens are saved to ~/.config/grokcli/auth.json (chmod 600) and refreshed\n"
            "automatically. No API key is used."
        ),
        epilog=(
            "EXAMPLES:\n"
            "  grokcli login                  local machine with a browser\n"
            "  grokcli login --no-browser     print the URL instead of opening a browser\n"
            "  grokcli login --manual-paste   SSH/remote/cloud-shell: paste the callback URL back\n"
            "  grokcli login --from-official  import an existing login from the official ~/.grok CLI\n\n"
            "NOTE: a 403 after a successful login means your subscription tier lacks API\n"
            "access — re-logging in will not help; upgrade at https://x.ai/grok."
        ),
    )
    login.add_argument("--no-browser", action="store_true", help="don't auto-open the browser; print the URL")
    login.add_argument("--manual-paste", action="store_true", help="paste the callback URL (headless/remote)")
    login.add_argument("--from-official", action="store_true", help="import an existing login from ~/.grok")
    login.set_defaults(func=_cmd_login)

    logout = _sub(
        sub, "logout", parent,
        help_text="remove stored credentials",
        description="Delete the stored OAuth credentials (~/.config/grokcli/auth.json).",
        epilog="EXAMPLES:\n  grokcli logout",
    )
    logout.set_defaults(func=_cmd_logout)

    status = _sub(
        sub, "status", parent,
        help_text="show login status and token expiry",
        description="Report whether you are logged in, the account, token expiry, and any last error.",
        epilog="EXAMPLES:\n  grokcli status\n  grokcli status --output json",
    )
    status.set_defaults(func=_cmd_status)


def _add_doctor_command(sub, parent) -> None:
    doc = _sub(
        sub, "doctor", parent,
        help_text="health check: auth, connectivity, entitlement",
        description=(
            "Run diagnostics: Python version, config dir, stored credentials, access-token\n"
            "validity, network reachability, token refresh, and an authenticated API ping.\n"
            "Exits non-zero (3 auth / 6 network / ...) if a check fails."
        ),
        epilog="EXAMPLES:\n  grokcli doctor             full check\n  grokcli doctor --offline   skip network/API checks",
    )
    doc.add_argument("--offline", action="store_true", help="skip network checks")
    doc.set_defaults(func=_cmd_doctor)


def _add_chat_commands(sub, parent) -> None:
    chat = _sub(
        sub, "chat", parent,
        help_text="chat with Grok (one-shot, stdin, or interactive REPL)",
        description=(
            "Chat with Grok. Provide PROMPT for a one-shot reply, pass '-' (or pipe stdin) to\n"
            "read the prompt from stdin, or omit PROMPT entirely for an interactive REPL\n"
            "(requires a terminal; type /help inside it). Replies stream by default.\n\n"
            "Conversations can be continued across separate invocations — history is stored\n"
            "locally and bounded (see `grokcli sessions`):\n"
            "  -c/--continue   resume the most recent conversation\n"
            "  --session NAME  use or create a named conversation\n"
            "  --new           start fresh (ignore -c)\n\n"
            "Let Grok search while answering (with citations): --web (web), --x (X/Twitter)."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli chat "Explain entropy simply"\n'
            '  grokcli chat "Summarize this" < article.txt\n'
            '  cat log.txt | grokcli chat -\n'
            '  grokcli chat -c "now in one sentence"\n'
            '  grokcli chat --session research "what did we conclude?"\n'
            '  grokcli chat "latest SpaceX launch?" --web --x\n'
            '  grokcli chat "in 3 words" --no-stream --output json | jq -r .text\n'
            "  grokcli chat                         interactive REPL (TTY only)"
        ),
    )
    chat.add_argument("prompt", nargs="?", help="prompt text; omit for a REPL, or '-' to read stdin")
    chat.add_argument("-m", "--model", default=None, help="model (default from config)")
    chat.add_argument("-s", "--system", default=None, help="system prompt / instructions")
    chat.add_argument("--no-stream", action="store_true", help="wait for the full reply instead of streaming")
    chat.add_argument("--web", action="store_true", help="enable web search")
    chat.add_argument("--x", action="store_true", help="enable X (Twitter) search")
    chat.add_argument("-c", "--continue", dest="continue_session", action="store_true", help="continue the most recent conversation")
    chat.add_argument("--session", default=None, help="continue/create a named session")
    chat.add_argument("--new", action="store_true", help="start a fresh session (ignore -c)")
    chat.add_argument("--effort", default=None, help="reasoning effort: low, medium, high (grok-4.6 rejects none)")
    chat.add_argument("--priority", action="store_true", help="request priority processing (service_tier)")
    chat.set_defaults(func=_cmd_chat)

    search = _sub(
        sub, "search", parent,
        help_text="search X + web, answered by Grok with citations",
        description=(
            "Ask Grok a question and let it search X (Twitter) and the web server-side,\n"
            "returning an answer with inline source citations. Both sources are on by default."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli search "who won the F1 race this weekend?"\n'
            '  grokcli search "xAI news this month" --no-x      web only\n'
            '  grokcli search "@grok recent posts" --no-web     X only'
        ),
    )
    search.add_argument("query", help="search query")
    search.add_argument("-m", "--model", default=None, help="model (default from config)")
    search.add_argument("--no-web", action="store_true", help="disable web search")
    search.add_argument("--no-x", action="store_true", help="disable X search")
    search.add_argument("--no-stream", action="store_true", help="wait for the full reply")
    search.add_argument("--effort", default=None, help="reasoning effort: low, medium, high (grok-4.6 rejects none)")
    search.set_defaults(func=_cmd_search)


def _add_media_commands(sub, parent) -> None:
    image = _sub(
        sub, "image", parent,
        help_text="generate image(s) from a text prompt",
        description=(
            "Generate one or more images and save them to ./grokcli-output/ (paths printed\n"
            "to stdout). Aspect ratios: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, plus wide/phone\n"
            "ratios and 'auto'. Resolution: 1k or 2k. Quality: low/medium/auto."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli image "a serene mountain lake at dawn"\n'
            '  grokcli image "flat vector logo, blue" -a 1:1 -r 2k -n 3'
        ),
    )
    image.add_argument("prompt", help="image description")
    image.add_argument("-m", "--model", default=None, help="image model (default grok-imagine-image-2.0)")
    image.add_argument("-a", "--aspect", default="1:1",
                       help="aspect ratio: 1:1 16:9 9:16 4:3 3:4 3:2 2:3 21:9 5:2 9:19.5 19.5:9 9:20 20:9 1:2 2:1 auto (default 1:1)")
    image.add_argument("-r", "--resolution", default="2k", help="resolution: 1k or 2k (default 2k)")
    image.add_argument("-n", "--count", type=int, default=1, help="number of images, up to 10 (default 1)")
    image.add_argument("-q", "--quality", default=None, choices=["low", "medium", "auto"],
                       help="rendering effort (API default auto = low for generation)")
    image.add_argument("--response-format", default=None, choices=["url", "b64_json"],
                       help="delivery shape from the API (default url; b64_json saves one round-trip)")
    image.set_defaults(func=_cmd_image)

    video = _sub(
        sub, "video", parent,
        help_text="generate a video (text-, image-, or reference-to-video)",
        description=(
            "Generate a video: the job is submitted, polled until ready, then downloaded to\n"
            "./grokcli-output/. The default model grok-imagine-video-1.5 handles all three modes\n"
            "with native 1080p (T2V/I2V; R2V is capped at 720p). Aspect: 1:1 16:9 9:16 4:3 3:4 3:2 2:3.\n"
            "Resolution: 480p/720p/1080p. Duration 1-15s (validated per model, not clamped).\n"
            "  text-to-video (T2V):       just give a prompt\n"
            "  image-to-video (I2V):      -i IMAGE  animate a start image\n"
            "  reference-to-video (R2V):  --ref IMG style/subject refs, repeatable\n"
            "  R2V narration:             --ref-audio VOICE preset voice, max 3; tag in the prompt\n"
            "                             as <AUDIO_0>, <AUDIO_1>, ... (1.5 only)\n"
            "I2V (-i) and R2V (--ref / --ref-audio) are mutually exclusive."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli video "a calm ocean wave at sunset" -d 6 -r 1080p\n'
            '  grokcli video "gently animate this portrait" -i photo.png\n'
            '  grokcli video "a character in this style, walking" --ref a.png --ref b.png\n'
            '  grokcli video "a chef narrates: <AUDIO_0> the recipe" --ref dish.jpg --ref-audio eve'
        ),
    )
    video.add_argument("prompt", help="video description")
    video.add_argument("-i", "--image", default=None, help="starting image for image-to-video (I2V)")
    video.add_argument("--ref", dest="reference_images", action="append", default=None,
                       help="reference image for reference-to-video (R2V); repeatable")
    video.add_argument("--ref-audio", dest="reference_audios", action="append", default=None,
                       help="preset voice for R2V narration; repeatable, max 3 (1.5 only)")
    video.add_argument("-m", "--model", default=None, help="video model (default grok-imagine-video-1.5)")
    video.add_argument("-a", "--aspect", default="16:9", help="aspect ratio (default 16:9)")
    video.add_argument("-r", "--resolution", default="720p", help="480p/720p/1080p (R2V capped at 720p; default 720p)")
    video.add_argument("-d", "--duration", type=int, default=8, help="seconds, 1-15 (default 8)")
    video.set_defaults(func=_cmd_video)

    image_edit = _sub(
        sub, "image-edit", parent,
        help_text="edit existing image(s) with a prompt",
        description=(
            "Edit up to 5 source images guided by a text prompt (POST /images/edits); the result\n"
            "is saved to ./grokcli-output/. Aspect ratio is optional (defaults to the input's,\n"
            "or 'auto' for multi-image edits). Use `image` instead for text-only generation."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli image-edit "make it night, add neon signs" -i street.png\n'
            '  grokcli image-edit "blend these into one scene" -i a.png -i b.png -a auto'
        ),
    )
    image_edit.add_argument("prompt", help="how to edit the image(s); reference sources as <IMAGE_0>, <IMAGE_1>, ...")
    image_edit.add_argument("-i", "--image", dest="sources", action="append", default=None,
                            help="source image (local path or URL); repeatable, up to 5")
    image_edit.add_argument("-m", "--model", default=None, help="image model (default grok-imagine-image-2.0)")
    image_edit.add_argument("-a", "--aspect", default=None, help="aspect ratio (default: follow input / auto)")
    image_edit.add_argument("-r", "--resolution", default=None, help="resolution: 1k or 2k (default: model default)")
    image_edit.add_argument("-n", "--count", type=int, default=1, help="number of variations, up to 10 (default 1)")
    image_edit.add_argument("-q", "--quality", default=None, choices=["low", "medium", "auto"],
                            help="rendering effort (API default auto = medium for edits)")
    image_edit.add_argument("--response-format", default=None, choices=["url", "b64_json"],
                            help="delivery shape from the API (default url; b64_json saves one round-trip)")
    image_edit.set_defaults(func=_cmd_image_edit)

    video_extend = _sub(
        sub, "video-extend", parent,
        help_text="extend an existing video",
        description=(
            "Extend a video by appending more generated footage (POST /videos/extensions);\n"
            "submitted, polled, then downloaded to ./grokcli-output/. The input may be a local\n"
            "video file or an http(s) URL. An optional prompt steers the continuation.\n"
            "Extension segments are 2-10s (the API range for this endpoint)."
        ),
        epilog=(
            "EXAMPLES:\n"
            "  grokcli video-extend clip.mp4\n"
            '  grokcli video-extend clip.mp4 "the camera pulls back to reveal a city" -d 6'
        ),
    )
    video_extend.add_argument("video", help="path or URL of the video to extend")
    video_extend.add_argument("prompt", nargs="?", default=None, help="optional continuation prompt")
    video_extend.add_argument("-m", "--model", default=None, help="video model (default grok-imagine-video; 1.5 rejects this endpoint)")
    video_extend.add_argument("-d", "--duration", type=int, default=6, help="seconds to add, 2-10 (default 6)")
    video_extend.set_defaults(func=_cmd_video_extend)

    video_edit = _sub(
        sub, "video-edit", parent,
        help_text="edit an existing video",
        description=(
            "Edit an existing video guided by a prompt (POST /videos/edits); submitted, polled,\n"
            "then downloaded to ./grokcli-output/. The input may be a local video file or an\n"
            "http(s) URL. The output keeps the input's length (capped at ~8.7s) and is capped\n"
            "at 720p."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli video-edit clip.mp4 "add a neon glow to the skyline"'
        ),
    )
    video_edit.add_argument("video", help="path or URL of the video to edit")
    video_edit.add_argument("prompt", help="edit instruction")
    video_edit.add_argument("-m", "--model", default=None, help="video model (default grok-imagine-video; 1.5 rejects this endpoint)")
    video_edit.set_defaults(func=_cmd_video_edit)

    tts = _sub(
        sub, "tts", parent,
        help_text="text-to-speech (save an audio file)",
        description=(
            "Synthesize speech from text and save it to ./grokcli-output/ (path printed to\n"
            "stdout). List available voice ids with `grokcli voices`; cloned custom voices\n"
            "(`grokcli voice clone`) work here too. Text is capped at 15,000 characters."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli tts "Hello from Grok" --voice Rex\n'
            '  grokcli tts "Bonjour le monde" --language fr -f wav\n'
            '  grokcli tts "slow and clear" --speed 0.8 --latency 2'
        ),
    )
    tts.add_argument("text", help="text to speak")
    tts.add_argument("--voice", default=None, help="voice id (see `grokcli voices`)")
    tts.add_argument("--language", default="en", help="language code (default en)")
    tts.add_argument("-m", "--model", default=None, help="accepted for compatibility; the TTS API has no model parameter")
    tts.add_argument("-f", "--format", default="mp3", dest="fmt", help="audio format: mp3 wav pcm mulaw alaw (default mp3)")
    tts.add_argument("--speed", type=float, default=None, help="speech rate multiplier, 0.7-1.5 (default 1.0)")
    tts.add_argument("--latency", type=int, default=None, help="streaming latency level: 0 best quality, 1, 2 lowest (default 0)")
    tts.add_argument("--normalize", action="store_true", help="expand numbers/abbreviations into spoken form")
    tts.set_defaults(func=_cmd_tts)

    voices = _sub(
        sub, "voices", parent,
        help_text="list available TTS voices",
        description="List the voice ids available for `grokcli tts --voice`.",
        epilog="EXAMPLES:\n  grokcli voices\n  grokcli voices --output json",
    )
    voices.set_defaults(func=_cmd_voices)

    transcribe = _sub(
        sub, "transcribe", parent,
        help_text="transcribe an audio file to text (ASR)",
        description=(
            "Transcribe a local audio file to text (printed to stdout). Audio formats:\n"
            "WAV, MP3, OGG, Opus, FLAC, AAC, MP4, M4A, MKV (auto-detected)."
        ),
        epilog=(
            "EXAMPLES:\n"
            "  grokcli transcribe meeting.mp3\n"
            "  grokcli transcribe call.wav --diarize --vad-threshold 0.3\n"
            "  grokcli transcribe note.wav --language en --keyterm Grok --keyterm API --output json"
        ),
    )
    transcribe.add_argument("audio", help="path to an audio file")
    transcribe.add_argument("-m", "--model", default=None, help="transcription model (default grok-transcribe)")
    transcribe.add_argument("--vad-threshold", type=float, default=None,
                            help="voice-activity gate, 0.0-1.0 (0 disables it; default 0.5)")
    transcribe.add_argument("--language", default=None,
                            help="language code for formatting (e.g. en); transcribes any language regardless")
    transcribe.add_argument("--diarize", action="store_true", help="label each word with a speaker")
    transcribe.add_argument("--keyterm", action="append", default=None,
                            help="key terms to recognize; repeatable (max 100 terms, 50 chars each)")
    transcribe.set_defaults(func=_cmd_transcribe)

    voice = _sub(
        sub, "voice", parent,
        help_text="clone, list, or delete custom voices",
        description=(
            "Manage custom (cloned) voices via the Custom Voices API. A clone uses a reference\n"
            "clip (max 120s; WAV recommended) and the returned voice_id works everywhere a\n"
            "built-in voice does — `grokcli tts --voice <id>` included. Note: cloning is\n"
            "currently US-only and gated to Enterprise plans; a 403 means your tier cannot\n"
            "create voices (listing may still work)."
        ),
        epilog=(
            "EXAMPLES:\n"
            '  grokcli voice clone my_clip.wav --name "Narrator"\n'
            "  grokcli voice list\n"
            "  grokcli voice delete <voice_id>\n"
            '  grokcli tts "hello" --voice <voice_id>     # use a cloned voice'
        ),
    )
    voice_sub = voice.add_subparsers(dest="voice_action", metavar="<action>")
    clone_p = _sub(voice_sub, "clone", parent, help_text="clone a voice from a reference clip",
                   description="Clone a voice from an audio clip (max 120s; WAV recommended).",
                   epilog="EXAMPLES:\n  grokcli voice clone clip.wav --name Narrator --gender neutral")
    clone_p.add_argument("audio", help="path to the reference clip")
    clone_p.add_argument("--name", default=None, help="voice name")
    clone_p.add_argument("--description", default=None, help="voice description")
    clone_p.add_argument("--gender", default=None, choices=["male", "female", "neutral"], help="speaker gender")
    clone_p.add_argument("--accent", default=None, help="speaker accent")
    clone_p.add_argument("--age", default=None, help="speaker age")
    clone_p.add_argument("--language", default=None, help="language (e.g. en)")
    clone_p.add_argument("--tone", default=None, help="voice tone")
    clone_p.set_defaults(func=_cmd_voice_clone)
    _sub(voice_sub, "list", parent, help_text="list cloned voices",
         description="List the custom voices on your team.",
         epilog="EXAMPLES:\n  grokcli voice list").set_defaults(func=_cmd_voice_list)
    delete_p = _sub(voice_sub, "delete", parent, help_text="delete a cloned voice",
                    description="Delete a custom voice by its voice_id.",
                    epilog="EXAMPLES:\n  grokcli voice delete abc12345")
    delete_p.add_argument("voice_id", help="the voice_id to delete")
    delete_p.set_defaults(func=_cmd_voice_delete)
    voice.set_defaults(func=_cmd_voice_list)


def _add_sessions_command(sub, parent) -> None:
    sessions = _sub(
        sub, "sessions", parent,
        help_text="manage saved chat conversations",
        description=(
            "Manage conversations saved by `grokcli chat -c` / `--session` under\n"
            "~/.config/grokcli/sessions/. Storage is bounded automatically: each session keeps\n"
            "only its most recent messages (GROKCLI_MAX_SESSION_MESSAGES, default 100) and only\n"
            "the most recent sessions are kept (GROKCLI_MAX_SESSIONS, default 50)."
        ),
        epilog=(
            "EXAMPLES:\n"
            "  grokcli sessions list           list saved conversations (newest first)\n"
            "  grokcli sessions show           print the most recent transcript\n"
            "  grokcli sessions show <id>      print a specific conversation\n"
            "  grokcli sessions clear <id>     delete one conversation\n"
            "  grokcli sessions clear --all    delete every saved conversation"
        ),
    )
    sess_sub = sessions.add_subparsers(dest="sessions_action", metavar="<action>")
    _sub(sess_sub, "list", parent, help_text="list saved sessions (newest first)",
         description="List saved conversations with turn count and a preview.",
         epilog="EXAMPLES:\n  grokcli sessions list").set_defaults(func=_cmd_sessions_list)
    show_p = _sub(sess_sub, "show", parent, help_text="print a session transcript",
                  description="Print a conversation transcript (defaults to the most recent).",
                  epilog="EXAMPLES:\n  grokcli sessions show\n  grokcli sessions show 20260603_014013_ab12cd")
    show_p.add_argument("id", nargs="?", help="session id (default: most recent)")
    show_p.set_defaults(func=_cmd_sessions_show)
    clear_p = _sub(sess_sub, "clear", parent, help_text="delete a session, or all",
                   description="Delete one saved conversation by id, or all of them with --all.",
                   epilog="EXAMPLES:\n  grokcli sessions clear <id>\n  grokcli sessions clear --all")
    clear_p.add_argument("id", nargs="?", help="session id to delete")
    clear_p.add_argument("--all", action="store_true", help="delete every session")
    clear_p.set_defaults(func=_cmd_sessions_clear)
    sessions.set_defaults(func=_cmd_sessions_list)


def _add_models_command(sub, parent) -> None:
    models = _sub(
        sub, "models", parent,
        help_text="list models available to your subscription",
        description="List the model ids available to your account (GET /v1/models).",
        epilog="EXAMPLES:\n  grokcli models\n  grokcli models --output json",
    )
    models.set_defaults(func=_cmd_models)


def _add_quota_command(sub, parent) -> None:
    quota = _sub(
        sub, "quota", parent,
        help_text="show subscription quota usage (credits, reset time)",
        description=(
            "Show your subscription's usage period and remaining credits\n"
            "(the quota surface behind the Grok app's usage meter; weekly for\n"
            "SuperGrok, with a per-product split when the account reports one)."
        ),
        epilog="EXAMPLES:\n  grokcli quota\n  grokcli quota --output json",
    )
    quota.set_defaults(func=_cmd_quota)


def _add_config_command(sub, parent) -> None:
    keys = "base_url, chat_model, image_model, video_model, tts_model, stt_model, tts_voice, output_dir, timeout, proxy"
    cfg = _sub(
        sub, "config", parent,
        help_text="view or change saved defaults",
        description=(
            "View or change saved defaults in ~/.config/grokcli/config.json.\n"
            f"Valid keys: {keys}.\n"
            "(base_url is pinned to x.ai / *.x.ai and rejected otherwise.)"
        ),
        epilog=(
            "EXAMPLES:\n"
            "  grokcli config show\n"
            "  grokcli config get chat_model\n"
            "  grokcli config set chat_model grok-4.6\n"
            "  grokcli config set output_dir ~/Pictures/grok\n"
            "  grokcli config path"
        ),
    )
    cfg_sub = cfg.add_subparsers(dest="config_action", metavar="<action>")
    _sub(cfg_sub, "show", parent, help_text="print all saved config values",
         description="Print the saved config file contents.",
         epilog="EXAMPLES:\n  grokcli config show").set_defaults(func=_cmd_config_show)
    _sub(cfg_sub, "path", parent, help_text="print the config file path",
         description="Print the path to the config file.",
         epilog="EXAMPLES:\n  grokcli config path").set_defaults(func=_cmd_config_path)
    get_p = _sub(cfg_sub, "get", parent, help_text="read one config value",
                 description=f"Read one saved config value. Keys: {keys}.",
                 epilog="EXAMPLES:\n  grokcli config get chat_model")
    get_p.add_argument("key")
    get_p.set_defaults(func=_cmd_config_get)
    set_p = _sub(cfg_sub, "set", parent, help_text="write one config value",
                 description=f"Set one saved config value. Keys: {keys}.",
                 epilog="EXAMPLES:\n  grokcli config set chat_model grok-4.6")
    set_p.add_argument("key")
    set_p.add_argument("value")
    set_p.set_defaults(func=_cmd_config_set)
    cfg.set_defaults(func=_cmd_config_show)


# -- settings ---------------------------------------------------------------


def _cmd_help(args, settings) -> int:
    """Print the whole manual (or one command's help) — a one-call guide for agents."""
    parser = build_parser()
    sub_action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    topic = getattr(args, "topic", None)
    if topic and sub_action is not None and topic in sub_action.choices:
        output.stdout(sub_action.choices[topic].format_help())
        return 0
    if topic:
        raise UsageError(f"Unknown command: {topic!r}.", hint="Run `grokcli help` to list all commands.")
    output.stdout(parser.format_help())
    if sub_action is not None:
        for name, subparser in sub_action.choices.items():
            output.stdout("\n" + "=" * 72 + f"\ngrokcli {name}\n" + "=" * 72)
            output.stdout(subparser.format_help())
    return 0


def _settings_from_args(args: argparse.Namespace) -> config.Settings:
    overrides: Dict[str, Any] = {
        "output_format": getattr(args, "output", None),
        "no_color": getattr(args, "no_color", False),
        "verbose": getattr(args, "verbose", False),
        "base_url": getattr(args, "base_url", None),
        "timeout": getattr(args, "timeout", None),
        "proxy": getattr(args, "proxy", None),
    }
    return config.resolve_settings({k: v for k, v in overrides.items() if v not in (None, False)})


# -- command handlers -------------------------------------------------------


def _cmd_login(args, settings) -> int:
    from .auth import login

    result = login.do_login(
        settings, no_browser=args.no_browser, manual_paste=args.manual_paste, from_official=args.from_official
    )
    account = result.get("account") or {}
    who = account.get("email") or account.get("user_id") or "your account"
    output.emit_result(settings.output_format, result, output.Style(settings.color).green(f"Logged in as {who}."))
    return 0


def _cmd_logout(args, settings) -> int:
    from .auth import login

    result = login.do_logout()
    text = "Logged out." if result["removed"] else "No stored credentials."
    output.emit_result(settings.output_format, result, text)
    return 0


def _cmd_status(args, settings) -> int:
    from .auth import login

    status = login.do_status(settings)
    output.emit_result(settings.output_format, status, _format_status(status, settings))
    return 0 if status.get("logged_in") else int(ExitCode.AUTH)


def _format_status(status: Mapping[str, Any], settings: config.Settings) -> str:
    style = output.Style(settings.color)
    if not status.get("logged_in"):
        return style.yellow("Not logged in.") + " Run `grokcli login`."
    account = status.get("account") or {}
    lines = [style.green("Logged in.")]
    if account.get("email"):
        lines.append(f"  account: {account['email']}")
    if status.get("expires_at"):
        lines.append(f"  token expires: {status['expires_at']}")
    if status.get("expiring"):
        lines.append("  " + style.yellow("token is expiring; it will refresh on next use"))
    if status.get("last_auth_error"):
        lines.append("  " + style.red(f"last error: {status['last_auth_error'].get('message', '')}"))
    return "\n".join(lines)


def _cmd_doctor(args, settings) -> int:
    from . import doctor

    report = doctor.run_doctor(settings, online=not args.offline)
    doctor.render_report(report, settings)
    return int(report.exit_code())


def _cmd_chat(args, settings) -> int:
    from .chat import run
    from .search import tools as search_tools

    model = args.model or settings.chat_model
    tools = search_tools.build_tools(web=args.web, x=args.x) or None
    prompt = _read_prompt(args.prompt)
    session_kwargs = {
        "continue_session": args.continue_session,
        "session_name": args.session,
        "force_new": args.new,
    }
    if prompt is None:
        return run.run_repl(
            settings, model=model, system=args.system, stream=not args.no_stream, tools=tools,
            effort=args.effort, priority=args.priority, **session_kwargs
        )
    return run.run_chat(
        settings, prompt=prompt, model=model, system=args.system, stream=not args.no_stream, tools=tools,
        effort=args.effort, priority=args.priority, **session_kwargs
    )


def _cmd_search(args, settings) -> int:
    from .chat import run
    from .search import tools as search_tools

    model = args.model or settings.chat_model
    tools = search_tools.build_tools(web=not args.no_web, x=not args.no_x) or None
    instructions = (
        "You are a research assistant. Use the available search tools to answer with "
        "current, accurate information, and cite your sources."
    )
    return run.run_chat(
        settings, prompt=args.query, model=model, system=instructions, stream=not args.no_stream,
        tools=tools, effort=args.effort,
    )


def _read_prompt(raw: Optional[str]) -> Optional[str]:
    """Resolve the prompt: '-' or piped stdin -> read stdin; None on a TTY -> REPL."""
    if raw == "-":
        return sys.stdin.read()
    if raw is None and not _stdin_is_tty():
        return sys.stdin.read()
    return raw


def _cmd_image(args, settings) -> int:
    from .media import image

    return image.run_image(
        settings, prompt=args.prompt, model=args.model, aspect_ratio=args.aspect, resolution=args.resolution,
        n=args.count, quality=args.quality, response_format=args.response_format,
    )


def _cmd_video(args, settings) -> int:
    from .media import video

    return video.run_video(
        settings,
        prompt=args.prompt,
        model=args.model,
        aspect_ratio=args.aspect,
        resolution=args.resolution,
        duration=args.duration,
        image=args.image,
        reference_images=args.reference_images,
        reference_audios=args.reference_audios,
    )


def _cmd_image_edit(args, settings) -> int:
    from .media import image

    return image.run_image_edit(
        settings,
        prompt=args.prompt,
        sources=args.sources or [],
        model=args.model,
        aspect_ratio=args.aspect,
        resolution=args.resolution,
        n=args.count,
        quality=args.quality,
        response_format=args.response_format,
    )


def _cmd_video_extend(args, settings) -> int:
    from .media import video

    return video.run_video_extend(
        settings, video=args.video, prompt=args.prompt, model=args.model, duration=args.duration
    )


def _cmd_video_edit(args, settings) -> int:
    from .media import video

    return video.run_video_edit(
        settings, video=args.video, prompt=args.prompt, model=args.model
    )


def _cmd_tts(args, settings) -> int:
    from .media import tts

    return tts.run_tts(
        settings, text=args.text, voice=args.voice, model=args.model, fmt=args.fmt, language=args.language,
        speed=args.speed, latency=args.latency, normalize=args.normalize,
    )


def _cmd_voices(args, settings) -> int:
    from .media import tts

    return tts.run_voices(settings)


def _cmd_voice_clone(args, settings) -> int:
    from .media import voice

    return voice.run_voice_clone(
        settings, audio_path=args.audio, name=args.name, description=args.description,
        gender=args.gender, accent=args.accent, age=args.age,
        language=args.language, tone=args.tone,
    )


def _cmd_voice_list(args, settings) -> int:
    from .media import voice

    return voice.run_voice_list(settings)


def _cmd_voice_delete(args, settings) -> int:
    from .media import voice

    return voice.run_voice_delete(settings, voice_id=args.voice_id)


def _cmd_transcribe(args, settings) -> int:
    from .media import transcribe

    return transcribe.run_transcribe(
        settings, audio_path=args.audio, model=args.model,
        vad_threshold=args.vad_threshold, language=args.language,
        diarize=args.diarize, keyterms=args.keyterm,
    )


def _cmd_sessions_list(args, settings) -> int:
    from .chat import session

    items = session.list_sessions()
    if settings.output_format == "json":
        output.print_json(items)
        return 0
    if not items:
        output.stdout("(no saved sessions)")
        return 0
    style = output.Style(settings.color)
    for item in items:
        output.stdout(f"{style.cyan(item['id'])}  {item['turns']} turns  {item['updated']}  {style.dim(item['preview'])}")
    return 0


def _cmd_sessions_show(args, settings) -> int:
    from .chat import session

    sess = session.load(args.id) if args.id else session.latest()
    if sess is None:
        raise UsageError("No such session." if args.id else "No saved sessions yet.")
    if settings.output_format == "json":
        output.print_json(sess.to_dict())
        return 0
    style = output.Style(settings.color)
    output.stdout(style.bold(f"session {sess.id} (model {sess.model})"))
    for msg in sess.messages:
        label = style.cyan("You") if msg.get("role") == "user" else style.green("Grok")
        output.stdout(f"\n{label} ▸ {msg.get('content', '')}")
    return 0


def _cmd_sessions_clear(args, settings) -> int:
    from .chat import session

    removed = session.clear(args.id, all_sessions=args.all)
    output.emit_result(settings.output_format, {"removed": removed}, f"Removed {removed} session(s).")
    return 0


def _cmd_models(args, settings) -> int:
    from .client import GrokClient

    data = GrokClient(settings).request_json("GET", "/models")
    ids = _model_ids(data)
    output.emit_result(settings.output_format, data, "\n".join(ids))
    return 0


def _cmd_quota(args, settings) -> int:
    from . import quota

    return quota.run_quota(settings)


def _model_ids(data: Any) -> List[str]:
    items: List[Any] = []
    if isinstance(data, dict):
        raw = data.get("data") or data.get("models")
        if isinstance(raw, list):
            items = raw
    ids = [str(m.get("id") or m.get("name")) for m in items if isinstance(m, dict)]
    return sorted(i for i in ids if i and i != "None")


def _cmd_config_show(args, settings) -> int:
    data = config.load_config_file()
    text = "\n".join(f"{k} = {v}" for k, v in sorted(data.items())) or "(no saved config)"
    output.emit_result(settings.output_format, data, text)
    return 0


def _cmd_config_path(args, settings) -> int:
    path = str(config.config_path())
    output.emit_result(settings.output_format, {"path": path}, path)
    return 0


def _cmd_config_get(args, settings) -> int:
    data = config.load_config_file()
    if args.key not in data:
        raise UsageError(f"No config value set for {args.key!r}.")
    output.emit_result(settings.output_format, {args.key: data[args.key]}, str(data[args.key]))
    return 0


def _cmd_config_set(args, settings) -> int:
    path = config.set_config_value(args.key, _coerce(args.value))
    output.emit_result(
        settings.output_format, {"set": args.key, "path": str(path)}, f"Set {args.key} (saved to {path})"
    )
    return 0


def _coerce(value: str) -> Any:
    """Coerce a CLI string into int/float when it clearly is one."""
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            continue
    return value


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False


# -- entrypoint -------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None) or not hasattr(args, "func"):
        parser.print_help(sys.stderr)
        return int(ExitCode.USAGE)

    try:
        settings = _settings_from_args(args)
        return int(args.func(args, settings) or 0)
    except KeyboardInterrupt:
        output.stderr("\nInterrupted.")
        return int(ExitCode.INTERRUPT)
    except GrokError as exc:
        _render_error(exc, args)
        return int(exc.exit_code)
    except BrokenPipeError:  # piping into head/less and closing early
        return 0


def _render_error(exc: GrokError, args: argparse.Namespace) -> None:
    if getattr(args, "output", None) == "json":
        import json

        sys.stderr.write(json.dumps({"error": exc.to_dict()}, ensure_ascii=False) + "\n")
        return
    style = output.Style(not getattr(args, "no_color", False))
    sys.stderr.write(style.red(f"Error: {exc.message}") + "\n")
    if exc.hint:
        sys.stderr.write(style.dim(f"  → {exc.hint}") + "\n")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
