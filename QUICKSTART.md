# Quick Start — Next Agent Handoff

**Project**: hermes-feishu-streaming-card  
**Mode**: Sidecar v2.1 (in progress)  
**Updated**: 20260417_171943

## Current Status

✅ Sidecar server running (PID 28851, port 8765)  
✅ /events endpoint working (200 OK, tested)  
✅ finalize_card logic fixed  
✅ Adapter modules complete (5 files)  
⏳ **Gateway patch needed** (blocking)

## Files Created in This Session

```
/Users/bailey/github/hermes-feishu-streaming-card/
├── PROJECT_SNAPSHOT_20260417_171943.json   ← Complete machine-readable state
├── TODO.md                             ← Task checklist
├── ISSUES.md                           ← Known issues
├── QUICKSTART.md                       ← This handoff doc
├── TECHNICAL_PROGRESS.md               ← Detailed technical notes (if created)
├── ENV_INFO.txt                        ← Environment paths
├── ARCHIVED_CODE/                      ← Key code snippets
│   ├── adapter_factory.py
│   ├── sidecar_adapter.py
│   └── gateway_forwarding.py
└── sidecar/
    ├── server.py
    ├── cardkit_client.py    ← finalize_card fixed
    ├── card_manager.py
    ├── config.py
    └── __main__.py
└── adapter/
    ├── streaming_adapter.py
    ├── legacy_adapter.py
    ├── sidecar_adapter.py
    ├── factory.py
    └── dual_adapter.py
```

## Immediate Task: Gateway Event Forwarding

**Target file**: `~/.hermes/hermes-agent/gateway/platforms/feishu.py`

**4 injection points** (see QUICKSTART.md for exact code blocks):

1. `__init__` (end): create `self._event_emitter = get_emitter(self)`
2. `_handle_message_with_agent` (start): emit `message_received`
3. `send` (inside streaming loop, after `yield delta_text`): emit `thinking`
4. `after_agent_hooks` (finalize block): emit `finish`

All emissions are `asyncio.create_task(emitter.emit(...))` — non-blocking.

## Quick Verification

```bash
# 1. Sidecar healthy?
curl http://localhost:8765/health
# → {"status":"healthy",...}

# 2. Restart gateway after patch
hermes gateway run --replace

# 3. Start chat
hermes chat

# 4. Send message that triggers streaming (with tool calls if possible)
# 5. Watch sidecar log:
tail -f ~/.hermes/logs/feishu-sidecar.log
# Expected lines:
#   [CardKit] Card created: <card_id> for chat <chat_id>
#   [CardKit] Text updated: thinking_content on card <card_id>
#   [CardKit] Card finalized: <card_id>
```

## Important Notes

- **finalize_card**: deletes `thinking_content`, adds `final_content` with footer (`🔢 输入: X | 输出: Y | 总计: Z | ⏱️ Ns`)
- **Event schema**: `{"event": "event_name", "data": {...}}` — sidecar validates `event` field
- **Adapter selection**: `config.yaml` → `feishu_streaming_card.mode` (`sidecar` | `legacy` | `dual`)
- **Failure handling**: sidecar unreachable → gateway should log warning and continue (no streaming)

## Environment

- Hermes home: `~/.hermes`
- Venv: `~/.hermes/hermes-agent/venv/bin/python3`
- Sidecar config: `~/.hermes/feishu-sidecar.yaml`
- Gateway log: `/tmp/hermes-gateway-*.log`
- Sidecar log: `~/.hermes/logs/feishu-sidecar.log`

**Running**: gateway PID 87647, sidecar PID 28851

---

*Handoff generated automatically. Read TODO.md for full task list, PROJECT_SNAPSHOT_*.json for machine-readable state.*
