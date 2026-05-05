from __future__ import annotations

from typing import Any, Dict

from .session import CardSession
from .text import normalize_stream_text

DEFAULT_FOOTER_FIELDS = (
    "duration",
    "model",
    "input_tokens",
    "output_tokens",
    "context",
)
MAIN_CONTENT_CHUNK_CHARS = 2400
DEFAULT_TITLE = "Hermes Agent"
SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

def render_card(
    session: CardSession,
    footer_fields: list[str] | tuple[str, ...] | None = None,
    title: str = DEFAULT_TITLE,
) -> Dict[str, Any]:
    status = _render_status(session)
    main_text = normalize_stream_text(session.visible_main_text) or ("正在思考..." if session.status == "thinking" else "")
    tool_summary = _render_tool_summary(session)
    footer = _render_footer(session, footer_fields)
    header_title = title.strip() if isinstance(title, str) and title.strip() else DEFAULT_TITLE
    elements = _render_main_content_elements(main_text)
    elements.extend(
        [
            {"tag": "hr", "element_id": "main_divider"},
            {"tag": "lark_md", "element_id": "tool_summary", "content": tool_summary},
            {"tag": "lark_md", "element_id": "footer", "content": footer, "text_size": "x-small"},
        ]
    )
    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "summary": {"content": status["subtitle"]},
        },
        "header": {
            "template": status["template"],
            "title": {"tag": "plain_text", "content": header_title},
            "subtitle": {"tag": "plain_text", "content": status["subtitle"]},
        },
        "body": {
            "elements": elements
        },
    }


def _render_status(session: CardSession) -> Dict[str, str]:
    if session.status == "completed":
        return {"subtitle": "已完成", "template": "green"}
    if session.status == "failed":
        return {"subtitle": "处理失败", "template": "red"}
    return {"subtitle": "思考中", "template": "indigo"}


def _render_main_content_elements(main_text: str) -> list[Dict[str, Any]]:
    # 飞书 markdown 忽略单换行；转为双空格+换行(=markdown软换行)使其可见
    text = main_text.replace("\n", "  \n")
    chunks = _split_text(text, MAIN_CONTENT_CHUNK_CHARS)
    elements = []
    for index, chunk in enumerate(chunks):
        element_id = "main_content" if index == 0 else f"main_content_{index}"
        elements.append({"tag": "lark_md", "element_id": element_id, "content": chunk})
    return elements


def _split_text(text: str, chunk_size: int) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]


def _render_tool_summary(session: CardSession) -> str:
    if not session.tools:
        return "工具调用 0 次"
    # 按工具名统计
    from collections import Counter
    name_counts = Counter(t.name for t in session.tools)
    lines = [f"工具调用 {session.tool_count} 次"]
    for name, count in name_counts.most_common():
        statuses = [t.status for t in session.tools if t.name == name]
        running = statuses.count("running")
        completed = statuses.count("completed")
        parts = [f"`{name}`: {count}次"]
        if completed:
            parts.append(f"{completed}完成")
        if running:
            parts.append(f"{running}执行中")
        lines.append("- " + ", ".join(parts))
    return "\n".join(lines)


def _render_footer(
    session: CardSession,
    footer_fields: list[str] | tuple[str, ...] | None = None,
) -> str:
    if session.status == "failed":
        return "已停止"
    if session.status != "completed":
        running_tools = [t for t in session.tools if t.status == "running"]
        if running_tools:
            spinner = SPINNER_FRAMES[session.heartbeat_count % len(SPINNER_FRAMES)]
            names = ", ".join(f"`{t.name}`" for t in running_tools[:2])
            if len(running_tools) > 2:
                names += f" +{len(running_tools)-2}"
            return f"{spinner} {names} 执行中"
        return "生成中"
    tokens = session.tokens if isinstance(session.tokens, dict) else {}
    input_tokens = _safe_int(tokens.get("input_tokens"))
    output_tokens = _safe_int(tokens.get("output_tokens"))
    try:
        duration = float(session.duration)
    except (TypeError, ValueError):
        duration = 0.0
    model = session.model if isinstance(session.model, str) and session.model.strip() else "Unknown"
    context = session.context if isinstance(session.context, dict) else {}
    used_context = _safe_int(context.get("used_tokens"))
    max_context = _safe_int(context.get("max_tokens"))
    context_percent = round(used_context / max_context * 100) if max_context > 0 else 0
    values = {
        "duration": _format_duration(duration),
        "model": model,
        "input_tokens": f"↑{_format_count(input_tokens)}",
        "output_tokens": f"↓{_format_count(output_tokens)}",
        "context": (
            f"ctx {_format_count(used_context)}/"
            f"{_format_count(max_context)} {context_percent}%"
        ),
    }
    selected = []
    fields = DEFAULT_FOOTER_FIELDS if footer_fields is None else footer_fields
    for field in fields:
        value = values.get(field)
        if value:
            selected.append(value)
    return " · ".join(selected) if selected else values["duration"]


def _safe_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{remaining_minutes}m{remaining_seconds}s"
    if minutes:
        return f"{minutes}m{remaining_seconds}s"
    return f"{remaining_seconds}s"


def _format_count(value: int) -> str:
    if value >= 1_000_000:
        return _format_scaled(value, 1_000_000, "m")
    if value >= 1_000:
        return _format_scaled(value, 1_000, "k")
    return str(value)


def _format_scaled(value: int, factor: int, suffix: str) -> str:
    scaled = value / factor
    if scaled >= 100 or scaled.is_integer():
        return f"{int(round(scaled))}{suffix}"
    return f"{scaled:.1f}".rstrip("0").rstrip(".") + suffix
