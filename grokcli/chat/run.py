"""Orchestration for ``grokcli chat`` (one-shot) and the interactive REPL.

Rendering follows the project's stream discipline: the assistant's answer goes
to stdout (so it pipes cleanly); prompts, spinners, and citations go to stderr.
In ``--output json`` mode the whole result is emitted as one JSON object and
streaming is disabled so stdout stays a single parseable document.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Mapping, Optional

from .. import output
from ..client import GrokClient
from ..config import Settings
from ..errors import GrokError, UsageError
from . import api, session


def run_chat(
    settings: Settings,
    *,
    prompt: str,
    model: str,
    system: Optional[str] = None,
    stream: bool = True,
    tools: Optional[List[Dict[str, Any]]] = None,
    env: Optional[Mapping[str, str]] = None,
    continue_session: bool = False,
    session_name: Optional[str] = None,
    force_new: bool = False,
    effort: Optional[str] = None,
    priority: bool = False,
) -> int:
    """Run a single-turn chat completion (optionally continuing a session)."""
    prompt = prompt.strip()
    if not prompt:
        raise UsageError("Empty prompt.", hint='Provide text: grokcli chat "your question"')
    client = GrokClient(settings, env=env)

    sess = None
    if continue_session or session_name:
        sess = session.resolve(
            continue_latest=continue_session, name=session_name, force_new=force_new,
            model=model, system=system, env=env,
        )
    prior = list(sess.messages) if sess else []
    effective_system = system or (sess.system if sess else None)
    messages = prior + [{"role": "user", "content": prompt}]

    if settings.output_format == "json" or not stream:
        result = api.complete(
            client, model=model, messages=messages, instructions=effective_system,
            tools=tools, effort=effort, priority=priority,
        )
        answer, citations = result["text"], result["citations"]
        output.emit_result(
            settings.output_format,
            {"text": answer, "citations": citations, "usage": result["usage"], "session": sess.id if sess else None},
            answer,
        )
        _print_citations(citations, settings)
    else:
        chat_stream = api.ChatStream(
            client, model=model, messages=messages, instructions=effective_system,
            tools=tools, effort=effort, priority=priority,
        )
        streamed_any = False
        for delta in chat_stream:
            sys.stdout.write(delta)
            sys.stdout.flush()
            streamed_any = True
        if streamed_any:
            sys.stdout.write("\n")
            sys.stdout.flush()
        elif chat_stream.text:
            output.stdout(chat_stream.text)
        answer, citations = chat_stream.text, chat_stream.citations
        _print_citations(citations, settings)

    if sess is not None:
        sess.add("user", prompt)
        sess.add("assistant", answer)
        if system:
            sess.system = system
        sess.model = model
        session.save(sess, env)
        output.stderr(output.Style(settings.color).dim(f"(session {sess.id})"))
    return 0


def _print_citations(citations: List[str], settings: Settings) -> None:
    if not citations or settings.output_format == "json":
        return
    style = output.Style(settings.color)
    output.stderr("\n" + style.dim("Sources:"))
    for index, url in enumerate(citations, 1):
        output.stderr(style.dim(f"  [{index}] {url}"))


REPL_HELP = """\
Commands:
  /help            show this help
  /reset           clear the conversation history
  /system <text>   set the system prompt
  /model <name>    switch model
  /exit, /quit     leave the REPL
"""


def run_repl(
    settings: Settings,
    *,
    model: str,
    system: Optional[str] = None,
    stream: bool = True,
    tools: Optional[List[Dict[str, Any]]] = None,
    env: Optional[Mapping[str, str]] = None,
    continue_session: bool = False,
    session_name: Optional[str] = None,
    force_new: bool = False,
    effort: Optional[str] = None,
    priority: bool = False,
) -> int:
    """Interactive multi-turn chat (persisted + resumable). Requires a TTY."""
    if not _stdin_is_tty():
        raise UsageError(
            "The REPL needs an interactive terminal.",
            hint='Pipe a single prompt instead: echo "hi" | grokcli chat -',
        )
    client = GrokClient(settings, env=env)
    style = output.Style(settings.color)
    sess = session.resolve(
        continue_latest=continue_session, name=session_name, force_new=force_new,
        model=model, system=system, env=env,
    )
    history = sess.messages
    system = system or sess.system
    resumed = " (resumed)" if history else ""
    output.stderr(style.bold(f"grokcli chat — model {model}, session {sess.id}{resumed}. /help, /exit."))

    while True:
        try:
            line = input(style.cyan("\nYou ▸ "))
        except (EOFError, KeyboardInterrupt):
            output.stderr("")
            return 0
        message = line.strip()
        if not message:
            continue
        if message.startswith("/"):
            action = _handle_command(message, history, style)
            if action == "exit":
                return 0
            if action == "set_system":
                system = message.split(" ", 1)[1].strip() if " " in message else None
                sess.system = system
            elif action == "set_model":
                model = message.split(" ", 1)[1].strip() or model
                sess.model = model
                output.stderr(style.dim(f"model → {model}"))
            elif action == "reset":
                session.save(sess, env)  # persist the now-empty history
            continue

        history.append({"role": "user", "content": message})
        try:
            answer = _exchange(
                client, model=model, history=history, system=system, stream=stream,
                tools=tools, style=style, effort=effort, priority=priority,
            )
        except GrokError as exc:
            # Keep the REPL alive on a failed turn; drop the dangling user message.
            history.pop()
            output.stderr(style.red(f"\nError: {exc.message}"))
            if exc.hint:
                output.stderr(style.dim(f"  → {exc.hint}"))
            continue
        history.append({"role": "assistant", "content": answer})
        sess.model = model
        session.save(sess, env)


def _exchange(client, *, model, history, system, stream, tools, style,
              effort=None, priority=False) -> str:
    sys.stdout.write(style.green("Grok ▸ "))
    sys.stdout.flush()
    if stream:
        chat_stream = api.ChatStream(
            client, model=model, messages=history, instructions=system,
            tools=tools, effort=effort, priority=priority,
        )
        for delta in chat_stream:
            sys.stdout.write(delta)
            sys.stdout.flush()
        sys.stdout.write("\n")
        return chat_stream.text
    result = api.complete(
        client, model=model, messages=history, instructions=system,
        tools=tools, effort=effort, priority=priority,
    )
    output.stdout(result["text"])
    return result["text"]


def _handle_command(message: str, history: List[Dict[str, str]], style: output.Style) -> str:
    command = message.split(" ", 1)[0].lower()
    if command in ("/exit", "/quit"):
        return "exit"
    if command == "/help":
        output.stderr(REPL_HELP)
        return "handled"
    if command == "/reset":
        history.clear()
        output.stderr(style.dim("history cleared"))
        return "reset"
    if command == "/system":
        return "set_system"
    if command == "/model":
        return "set_model"
    output.stderr(style.yellow(f"Unknown command: {command} (try /help)"))
    return "handled"


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, ValueError):
        return False
