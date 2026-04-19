#!/usr/bin/env python3
"""
gateway_run_patch.py — Adaptive injector for Feishu Streaming Card

Scans the user's run.py to find injection points dynamically.
Works regardless of Hermes version indentation differences.

Injection points:
1. message_received: after _msg_start_time assignment inside _handle_message_with_agent
2. finish: after agent:end hook completes
"""

import re
import ast
from pathlib import Path


# Injection code for message_received event (8-space indentation for _handle_message_with_agent body)
MESSAGE_RECEIVED_INJECTION = """
        # ── Feishu Streaming Card Sidecar Event Forwarding ─────────────────────
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
        # ────────────────────────────────────────────────────────────────────────"""

# Injection code for finish event (12-space indentation for try block inside _handle_message_with_agent)
FINISH_INJECTION = """
            # ── Feishu Streaming Card Sidecar Finish Event ─────────────────────
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
                            'last_prompt_tokens': agent_result.get('last_prompt_tokens', 0) or agent_result.get('input_tokens', 0),
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
            # ───────────────────────────────────────────────────────────────────"""


def find_function_bounds(content: str, func_signature_pattern: str) -> tuple:
    """Find a function's start and end line (0-indexed)."""
    lines = content.split('\n')
    
    func_start = None
    func_indent = None
    for i, line in enumerate(lines):
        if re.search(func_signature_pattern, line):
            func_start = i
            func_indent = len(line) - len(line.lstrip())
            break
    
    if func_start is None:
        return None, None, None
    
    func_end = None
    for i in range(func_start + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        
        indent = len(line) - len(line.lstrip())
        if indent <= func_indent and (stripped.startswith('def ') or 
                                       stripped.startswith('class ') or 
                                       stripped.startswith('async def ')):
            func_end = i
            break
    
    if func_end is None:
        func_end = len(lines)
    
    return func_start, func_end, func_indent


def find_pattern_in_function(content: str, func_start: int, func_end: int, patterns: list) -> int:
    """Find a line matching any of the patterns within a function range."""
    lines = content.split('\n')
    for i in range(func_start, min(func_end, len(lines))):
        line = lines[i]
        for pattern in patterns:
            if re.search(pattern, line):
                return i
    return None


def analyze_run_py(content: str) -> dict:
    """Analyze run.py and report what we found."""
    analysis = {
        'has_handle_message': False,
        'has_msg_start_time': False,
        'has_agent_end': False,
        'handle_message_line': None,
        'msg_start_line': None,
        'agent_end_line': None,
        'agent_end_indent': None,
    }
    
    lines = content.split('\n')
    
    for i, line in enumerate(lines):
        if 'async def _handle_message_with_agent' in line or 'def _handle_message_with_agent' in line:
            analysis['has_handle_message'] = True
            analysis['handle_message_line'] = i + 1
            break
    
    for i, line in enumerate(lines):
        if '_msg_start_time' in line and '=' in line and 'time.time()' in line:
            analysis['has_msg_start_time'] = True
            analysis['msg_start_line'] = i + 1
            break
    
    for i, line in enumerate(lines):
        if 'agent:end' in line and 'hooks.emit' in line:
            analysis['has_agent_end'] = True
            analysis['agent_end_line'] = i + 1
            analysis['agent_end_indent'] = len(line) - len(line.lstrip())
            break
    
    return analysis


def find_brace_end(lines, start_idx: int) -> int:
    """Find the closing brace for an open brace, handling strings."""
    depth = 0
    in_string = False
    string_char = None
    
    for i in range(start_idx, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            c = line[j]
            
            if not in_string and c in ('"', "'"):
                in_string = True
                string_char = c
                j += 1
                continue
            
            if in_string:
                if c == '\\' and j + 1 < len(line):
                    j += 2
                    continue
                if c == string_char:
                    in_string = False
                    string_char = None
                j += 1
                continue
            
            if c in '({':
                depth += 1
            elif c in ')}':
                depth -= 1
                if depth == 0:
                    return i
            
            j += 1
    
    return None


def patch_run_py():
    RUN_PY_PATH = Path.home() / ".hermes" / "hermes-agent" / "gateway" / "run.py"
    
    if not RUN_PY_PATH.exists():
        print(f"ERROR: {RUN_PY_PATH} not found")
        return False
    
    original = RUN_PY_PATH.read_text(encoding='utf-8')
    
    if 'Feishu Streaming Card Sidecar Event Forwarding' in original:
        print("INFO: Already patched")
        return True
    
    print("Analyzing Hermes run.py structure...")
    analysis = analyze_run_py(original)
    
    print(f"  _handle_message_with_agent: {'found' if analysis['has_handle_message'] else 'NOT FOUND'} (line {analysis['handle_message_line']})")
    print(f"  _msg_start_time = time.time(): {'found' if analysis['has_msg_start_time'] else 'NOT FOUND'} (line {analysis['msg_start_line']})")
    print(f"  agent:end hook: {'found' if analysis['has_agent_end'] else 'NOT FOUND'} (line {analysis['agent_end_line']}, indent {analysis['agent_end_indent']})")
    
    # Find function bounds
    func_start, func_end, func_indent = find_function_bounds(
        original,
        r'async def _handle_message_with_agent|def _handle_message_with_agent'
    )
    
    if func_start is None:
        print("\nERROR: Could not find _handle_message_with_agent function")
        print("  The Hermes version may have renamed this function.")
        print("  Please report this at: https://github.com/baileyh8/hermes-feishu-streaming-card/issues")
        return False
    
    print(f"\nFound _handle_message_with_agent at lines {func_start+1}-{func_end+1}")
    
    # Find _msg_start_time
    msg_start_idx = find_pattern_in_function(
        original, func_start, func_end,
        [r'_msg_start_time\s*=\s*time\.time\(\)', r'_msg_start_time\s*=\s*.*time']
    )
    
    if msg_start_idx is None:
        print("\nERROR: Could not find _msg_start_time assignment in _handle_message_with_agent")
        print("  The Hermes version may have changed how message timing is tracked.")
        print("  Please report this at: https://github.com/baileyh8/hermes-feishu-streaming-card/issues")
        return False
    
    print(f"Found _msg_start_time at line {msg_start_idx+1}")
    
    # Find agent:end hook
    agent_end_start = find_pattern_in_function(
        original, func_start, func_end,
        [r'await self\.hooks\.emit\(["\']agent:end["\']']
    )
    
    if agent_end_start is None:
        print("\nERROR: Could not find agent:end hook in _handle_message_with_agent")
        print("  The Hermes version may have changed how agent:end is emitted.")
        print("  Please report this at: https://github.com/baileyh8/hermes-feishu-streaming-card/issues")
        return False
    
    # Find closing }) of the emit call
    agent_end_end = find_brace_end(original.split('\n'), agent_end_start)
    
    if agent_end_end is None:
        print("\nERROR: Could not find end of agent:end hook call")
        return False
    
    print(f"Found agent:end at lines {agent_end_start+1}-{agent_end_end+1}")
    
    lines = original.split('\n')
    
    # Determine indentation for finish injection based on agent:end indent
    agent_indent = len(lines[agent_end_start]) - len(lines[agent_end_start].lstrip())
    
    # Adjust finish injection indentation to match agent:end context
    # The agent:end emit is inside a try block with 12 spaces, but the closing }) 
    # is at 12 spaces, so we insert at the same level
    adjusted_finish = FINISH_INJECTION
    
    # Find the base indentation level in FINISH_INJECTION (it's 12 spaces)
    base_indent = 12
    # We need to adjust to match agent_indent
    indent_diff = agent_indent - base_indent
    
    if indent_diff != 0:
        # Re-indent the FINISH_INJECTION
        adjusted_lines = []
        for line in FINISH_INJECTION.split('\n'):
            if line.strip():
                current_indent = len(line) - len(line.lstrip())
                new_indent = current_indent + indent_diff
                adjusted_lines.append(' ' * new_indent + line.lstrip())
            else:
                adjusted_lines.append(line)
        adjusted_finish = '\n'.join(adjusted_lines)
    
    # Insert injections (in reverse order to preserve line numbers)
    lines.insert(agent_end_end + 1, adjusted_finish)
    lines.insert(msg_start_idx + 1, MESSAGE_RECEIVED_INJECTION)
    
    # Validate syntax
    try:
        import ast
        result = '\n'.join(lines)
        ast.parse(result)
    except SyntaxError as e:
        print(f"\nERROR: Patched code has syntax error: {e}")
        print("This is a bug in the patch script. Please report at:")
        print("  https://github.com/baileyh8/hermes-feishu-streaming-card/issues")
        return False
    
    # Backup and write
    backup = RUN_PY_PATH.with_suffix('.py.backup')
    if not backup.exists():
        backup.write_text(original, encoding='utf-8')
        print(f"\nBackup saved: {backup}")
    
    RUN_PY_PATH.write_text(result, encoding='utf-8')
    print(f"Successfully patched run.py")
    return True


if __name__ == '__main__':
    import sys
    sys.exit(0 if patch_run_py() else 1)
