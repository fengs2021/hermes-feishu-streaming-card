from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .events import SidecarEvent
from .text import StreamingTextNormalizer, normalize_stream_text


@dataclass
class ToolState:
    tool_id: str
    name: str
    status: str
    detail: str = ""


@dataclass
class CardSession:
    conversation_id: str
    message_id: str
    chat_id: str
    status: str = "thinking"
    last_sequence: int = -1
    thinking_text: str = ""
    answer_text: str = ""
    tools: List[ToolState] = field(default_factory=list)
    tokens: Dict[str, Any] = field(default_factory=dict)
    model: str = "Unknown"
    context: Dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    thinking_normalizer: StreamingTextNormalizer = field(default_factory=StreamingTextNormalizer)
    answer_normalizer: StreamingTextNormalizer = field(default_factory=StreamingTextNormalizer)
    heartbeat_count: int = 0
    _tool_seq: int = 0

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    @property
    def visible_main_text(self) -> str:
        if self.status in {"completed", "failed"}:
            return self.answer_text
        if self.answer_text:
            return self.answer_text
        return self.thinking_text

    def apply(self, event: SidecarEvent) -> bool:
        if (
            event.conversation_id != self.conversation_id
            or event.message_id != self.message_id
            or event.chat_id != self.chat_id
        ):
            return False
        is_terminal_event = event.event in {"message.completed", "message.failed"}
        if event.sequence <= self.last_sequence and not is_terminal_event:
            return False
        if self.status in {"completed", "failed"}:
            return False
        self.last_sequence = max(self.last_sequence, event.sequence)

        if event.event == "thinking.delta":
            self.thinking_text += self.thinking_normalizer.feed(str(event.data.get("text", "")))
        elif event.event == "answer.delta":
            self.answer_text += self.answer_normalizer.feed(str(event.data.get("text", "")))
        elif event.event == "tool.updated":
            name = event.data.get("name")
            if not isinstance(name, str) or not name.strip():
                return True
            name = name.strip()
            status = event.data.get("status") or "running"
            detail = event.data.get("detail") or ""
            # 查找同名未完成的条目更新状态，否则追加新条目
            existing = _find_tool(self.tools, name, status, detail)
            if existing:
                existing.status = status
                existing.detail = detail
            else:
                self._tool_seq += 1
                self.tools.append(ToolState(
                    tool_id=f"t{self._tool_seq}",
                    name=name,
                    status=status,
                    detail=detail,
                ))
        elif event.event == "message.completed":
            self.status = "completed"
            self.answer_text = normalize_stream_text(str(event.data.get("answer") or self.answer_text))
            tokens = event.data.get("tokens", {})
            self.tokens = dict(tokens) if isinstance(tokens, dict) else {}
            model = event.data.get("model")
            self.model = model if isinstance(model, str) and model.strip() else "Unknown"
            context = event.data.get("context", {})
            self.context = dict(context) if isinstance(context, dict) else {}
            try:
                self.duration = float(event.data.get("duration", 0.0))
            except (TypeError, ValueError):
                self.duration = 0.0
        elif event.event == "message.failed":
            self.status = "failed"
            error = event.data.get("error")
            self.answer_text = error if isinstance(error, str) else "消息处理失败"
        return True


def _find_tool(tools: List[ToolState], name: str, status: str, detail: str) -> ToolState | None:
    """查找同名最近一个条目：running事件总是新增；completed事件更新最近running条目。"""
    if status == "running":
        return None
    # completed 事件：找最近一个同名 running 条目
    for t in reversed(tools):
        if t.name == name and t.status == "running":
            return t
    return None
