#!/usr/bin/env python3
"""
gateway_run_patch.py — Inject sidecar event forwarding into run.py

Patches Gateway's _handle_message_with_agent() to forward Feishu events
to the streaming card sidecar (non-blocking, exception-isolated).

Two injection points:
1. message_received: after _msg_start_time (inside _handle_message_with_agent)
2. finish: after agent:end hook completes
"""

import re
from pathlib import Path

# Path to Hermes gateway run.py
RUN_PY_PATH = Path.home() / ".hermes" / "hermes-agent" / "gateway" / "run.py"

# Injection code for message_received event
MESSAGE_RECEIVED_INJECTION = """
        # ── Feishu Streaming Card Sidecar Event Forwarding ─────────────────────
        # Config-driven: feishu_streaming_card.mode = "sidecar" | "legacy" | "disabled"
        # Non-blocking: fire-and-forget, exceptions handled in emitter
        try:
            _fsc_mode = None
            try:
                import yaml as _yaml
                with open(str(self._hermes_dir / "config.yaml")) as _f:
                    _cfg = _yaml.safe_load(_f) or {}
                _fsc_mode = (_cfg.get("feishu_streaming_card", {}) or {}).get("mode", "disabled")
            except Exception:
                pass

            if _fsc_mode == "sidecar" and source.platform.value == "feishu":
                from gateway.platforms.feishu_forward import get_emitter
                import asyncio
                import time as _time

                _emitter = getattr(self, '_feishu_sidecar_emitter', None)
                if _emitter is None:
                    _emitter = get_emitter(None, mode="sidecar")
                    self._feishu_sidecar_emitter = _emitter

                _payload = {
                    'chat_id': source.chat_id,
                    'user_id': source.user_id,
                    'user_name': source.user_name,
                    'text': event.text[:500] if event.text else '',
                    'timestamp': _time.time(),
                }
                asyncio.create_task(_emitter.emit('message_received', _payload))
        except Exception:
            pass
        # ────────────────────────────────────────────────────────────────────────
"""

# Injection code for finish event
FINISH_INJECTION = """
        # ── Feishu Streaming Card Sidecar Finish Event ─────────────────────────
        try:
            _fsc_mode = None
            try:
                import yaml as _yaml
                with open(str(self._hermes_dir / "config.yaml")) as _f:
                    _cfg = _yaml.safe_load(_f) or {}
                _fsc_mode = (_cfg.get("feishu_streaming_card", {}) or {}).get("mode", "disabled")
            except Exception:
                pass

            if _fsc_mode == "sidecar" and source.platform.value == "feishu":
                _emitter = getattr(self, '_feishu_sidecar_emitter', None)
                if _emitter is not None:
                    import time as _time
                    _duration = _time.time() - _msg_start_time
                    _tokens = {
                        'input_tokens': agent_result.get('input_tokens', 0),
                        'output_tokens': agent_result.get('output_tokens', 0),
                        'cache_read_tokens': agent_result.get('cache_read_tokens', 0),
                        'api_calls': agent_result.get('api_calls', 0),
                    }
                    _finish_payload = {
                        'chat_id': source.chat_id,
                        'final_content': (response or '')[:1000],
                        'tokens': _tokens,
                        'duration': _duration,
                        'thinking_start': _msg_start_time,
                    }
                    asyncio.create_task(_emitter.emit('finish', _finish_payload))
        except Exception:
            pass
        # ────────────────────────────────────────────────────────────────────────
"""


def find_pattern_end(lines, start_idx, open_char="(", close_char=")"):
    """Find the line index where a matching close char is found."""
    depth = 0
    for i in range(start_idx, len(lines)):
        line = lines[i]
        for c in line:
            if c == open_char:
                depth += 1
            elif c == close_char:
                depth -= 1
                if depth == 0:
                    return i
    return None


def patch_run_py():
    if not RUN_PY_PATH.exists():
        print(f"ERROR: {RUN_PY_PATH} not found")
        return False

    original = RUN_PY_PATH.read_text(encoding='utf-8')
    lines = original.splitlines(keepends=True)

    if 'Feishu Streaming Card Sidecar Event Forwarding' in original:
        print("INFO: Already patched")
        return True

    # Find _handle_message_with_agent
    target_idx = None
    for i, line in enumerate(lines):
        if 'async def _handle_message_with_agent(self, event, source, _quick_key: str):' in line:
            target_idx = i
            break

    if target_idx is None:
        print("ERROR: Could not find _handle_message_with_agent")
        return False

    # Find _msg_start_time = time.time() within _handle_message_with_agent
    msg_start_idx = None
    for i in range(target_idx + 1, min(target_idx + 20, len(lines))):
        if '_msg_start_time' in lines[i] and 'time.time()' in lines[i]:
            msg_start_idx = i
            break

    if msg_start_idx is None:
        print("ERROR: Could not find _msg_start_time")
        return False

    # Insert after the line containing _msg_start_time
    insert_idx = msg_start_idx + 1
    lines.insert(insert_idx, MESSAGE_RECEIVED_INJECTION + "\n")
    print(f"✓ Injected message_received at line {insert_idx + 1}")

    # Find the agent:end hook call and insert finish event after it completes
    # Pattern: await self.hooks.emit("agent:end", { ... })
    # We need to find the closing }) of this call
    agent_end_start = None
    for i in range(target_idx, len(lines)):
        if 'await self.hooks.emit("agent:end"' in lines[i] or "await self.hooks.emit('agent:end'" in lines[i]:
            agent_end_start = i
            break

    if agent_end_start is not None:
        # Find the end of this hook call - it's a multi-line call ending with })
        # The opening { is on the same line or next line, we need to track depth
        # Actually, let's find the closing }) after the start
        # We track depth starting at 1 for the opening { after emit(
        agent_end_end = find_pattern_end(lines, agent_end_start, "{", "}")
        if agent_end_end is not None:
            # Insert after the closing }) line
            finish_insert_idx = agent_end_end + 1
            # Skip any blank lines
            while finish_insert_idx < len(lines) and not lines[finish_insert_idx].strip():
                finish_insert_idx += 1
            lines.insert(finish_insert_idx, FINISH_INJECTION + "\n")
            print(f"✓ Injected finish event at line {finish_insert_idx + 1}")
        else:
            print("WARNING: Could not find agent:end hook end")
    else:
        print("WARNING: Could not find agent:end hook")

    # Backup
    backup = RUN_PY_PATH.with_suffix('.py.backup')
    if not backup.exists():
        backup.write_text(original, encoding='utf-8')
        print(f"Backup: {backup}")

    RUN_PY_PATH.write_text(''.join(lines), encoding='utf-8')
    print(f"✓ Patched run.py successfully")
    return True


if __name__ == '__main__':
    import sys
    sys.exit(0 if patch_run_py() else 1)
