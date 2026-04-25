#!/usr/bin/env bash
# Enforces uv-based Python conventions from CLAUDE.md.
# Blocks bare python/pip/pytest calls that should go through uv.
cmd=$(uv run python -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

if echo "$cmd" | grep -qE '(^|[;&|]\s*)(python3?)(\s|$)' && ! echo "$cmd" | grep -q 'uv'; then
  printf '{"continue":false,"stopReason":"Wrong CLI: use `uv run python` not bare python/python3. See CLAUDE.md."}'
  exit 0
fi

if echo "$cmd" | grep -qE '(^|[;&|]\s*)(pip3?)(\s|$)' && ! echo "$cmd" | grep -q 'uv pip'; then
  printf '{"continue":false,"stopReason":"Wrong CLI: use `uv pip install` not bare pip/pip3. See CLAUDE.md."}'
  exit 0
fi

if echo "$cmd" | grep -qE '(^|[;&|]\s*)pytest(\s|$)' && ! echo "$cmd" | grep -q 'uv run pytest'; then
  printf '{"continue":false,"stopReason":"Wrong CLI: use `uv run pytest` not bare pytest. See CLAUDE.md."}'
  exit 0
fi
