# Hermes Feishu Streaming Card - Todo List

## P0 (阻塞)
- [ ] Gateway event forwarding (feishu.py patch)
- [ ] Verify event payload format matches sidecar expectations

## P1 (重要)
- [ ] End-to-end test (Hermes chat → Feishu card with streaming)
- [ ] Graceful degradation (sidecar down → no crash, warning log)
- [ ] Dual-mode verification (legacy + sidecar parallel)

## P2 (优化)
- [ ] Installer enhancements
- [ ] Environment setup scripts
- [ ] Recovery script
- [ ] Prometheus metrics on gateway side
- [ ] Upgrade documentation
- [ ] GitHub release (v2.1-stable)

## Completed ✓
- [x] Sidecar `/events` 200 OK (fixed stale process)
- [x] finalize_card corrected (delete thinking_content, add final_content)
- [x] Adapter architecture (5 modules)
- [x] Sidecar HTTP server (aiohttp)
- [x] CardKit client (create/update/finalize)
- [x] CardManager with per-chat locking
- [x] Sidecar CLI
