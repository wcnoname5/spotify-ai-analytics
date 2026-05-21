# Sub-project A — Tool Registry (canonical tool layer + dual adapter)

**Date:** 2026-05-15
**Status:** Draft, awaiting review
**Parent roadmap:** [2026-05-15-chatbot-platform-roadmap.md](./2026-05-15-chatbot-platform-roadmap.md)
**Depends on:** —
**Blocks:** B (experiment infra), C (Chainlit shell), F (multi-model)

---

## 1. Goal

Move the canonical definition of every Spotify-analytics tool out of the MCP layer (`apps/mcp/spotify_mcp/`) into the shared core (`packages/core/spotify_core/tools/`). The MCP server becomes a thin adapter that re-exports the registry. The future Chainlit agent's LangChain `BaseTool` set is generated from the same registry. One function, two interfaces.

This refactor must be **invisible to existing MCP clients** (Claude Desktop, Claude Code): tool names, input schemas, return shapes, error responses, and `annotations` (`readOnlyHint` etc.) must be byte-identical before and after.

## 2. Why this is the first sub-project

- Every later sub-project (B's eval CLI, C's Chainlit agent, D's variants, F's model comparison) needs tool access without going through MCP/stdio. The IPC overhead is unnecessary in-process and makes telemetry/debug harder.
- Tool count is currently ~15; refactor cost is roughly linear in tool count. Doing it later — after Skills (G) and validation variants (D) add more dependencies on the tool surface — costs significantly more.
- Doing it first means **all subsequent work uses the new interface from day one**, avoiding a second migration.

## 3. Non-goals

- No new tools. No deleted tools. No renamed tools.
- No changes to tool *behavior*. Bug fixes deferred unless they are blocking the refactor.
- No changes to `spotify_core.analytics`, `spotify_core.db`, `spotify_core.spotify_client` — the registry wraps these unchanged.
- No skill loading, no agent code. Those come in C and G.

## 4. Current state (as of 2026-05-15)

Each MCP tool is defined inline inside a `register(mcp: FastMCP)` function using `@mcp.tool(...)` decorators. Locations:

| File | Tools owned |
|---|---|
| `apps/mcp/spotify_mcp/_mcp.py` | `setup_check` |
| `apps/mcp/spotify_mcp/db_crud.py` | `sync_history`, `import_history_from_json`, `get_listening_summary`, `get_top_artists`, `get_top_tracks` |
| `apps/mcp/spotify_mcp/spotify_control.py` | `get_now_playing`, `play_track`, `pause_playback`, `skip_track`, `set_volume`, `add_to_queue`, `create_playlist` |
| `apps/mcp/spotify_mcp/memory_store.py` | `remember_preference`, `get_memory_summary` |

Each tool body is small: validate inputs (Pydantic `Field` via `Annotated`), call into `spotify_core` for the heavy lifting, wrap errors with `to_error_response`, return a `dict`. Tool docstrings are the LLM-facing descriptions.

## 5. Target architecture

### 5.1 New package: `packages/core/spotify_core/tools/`

```
packages/core/spotify_core/tools/
    __init__.py          # exports: registry, ToolSpec, spotify_tool
    registry.py          # ToolRegistry + ToolSpec dataclass + @spotify_tool decorator
    analytics.py         # sync_history, import_history_from_json, get_listening_summary,
                         #   get_top_artists, get_top_tracks
    playback.py          # get_now_playing, play_track, pause_playback, skip_track,
                         #   set_volume, add_to_queue, create_playlist
    memory.py            # remember_preference, get_memory_summary
    diagnostics.py       # setup_check
    adapters/
        __init__.py
        mcp_adapter.py   # ToolSpec -> FastMCP @tool registration
        langchain_adapter.py   # ToolSpec -> langchain_core.tools.StructuredTool
```

### 5.2 `ToolSpec` dataclass

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str                          # canonical name, snake_case
    func: Callable                     # the implementation (sync; async deferred)
    description: str                   # extracted from func.__doc__; LLM-facing
    args_schema: type[BaseModel]       # Pydantic model auto-generated from signature
    annotations: dict[str, Any]        # MCP hints: readOnlyHint, idempotentHint, etc.
    category: Literal["analytics", "playback", "memory", "diagnostics"]
    requires_auth: bool                # mirrors the "Requires auth" column in MCP_QUICKSTART
```

### 5.3 `@spotify_tool` decorator

```python
@spotify_tool(
    category="analytics",
    requires_auth=True,
    annotations={"readOnlyHint": False, "idempotentHint": True, "openWorldHint": True},
)
def sync_history(
    user_id: Annotated[str, Field(description="...")] = DEFAULT_USER_ID,
) -> dict:
    """Fetch the 50 most recent Spotify plays ..."""
    # body unchanged from current implementation
```

The decorator:
- Reads the function's signature + docstring to build the `ToolSpec`
- Synthesizes a Pydantic `args_schema` from the `Annotated[..., Field(...)]` parameters (FastMCP already does this; the implementation can use FastMCP's existing helper or `pydantic.create_model`)
- Appends to a module-level `registry: ToolRegistry`
- Returns the function unchanged (so it can also be called directly in tests / from the agent)

### 5.4 `ToolRegistry`

```python
class ToolRegistry:
    def register(self, spec: ToolSpec) -> None: ...
    def all(self) -> list[ToolSpec]: ...
    def get(self, name: str) -> ToolSpec: ...
    def by_category(self, category: str) -> list[ToolSpec]: ...

registry = ToolRegistry()  # singleton populated by @spotify_tool at import time
```

### 5.5 MCP adapter

Replaces the current `register(mcp)` functions:

```python
# packages/core/spotify_core/tools/adapters/mcp_adapter.py
def attach_to_mcp(mcp: FastMCP, specs: Iterable[ToolSpec]) -> None:
    for spec in specs:
        mcp.tool(name=spec.name, annotations=spec.annotations)(spec.func)
```

`apps/mcp/spotify_mcp/_mcp.py` shrinks to:

```python
from spotify_core.tools import registry
from spotify_core.tools.adapters.mcp_adapter import attach_to_mcp

mcp = FastMCP("spotify_mcp", lifespan=lifespan)
register_prompts(mcp)
attach_to_mcp(mcp, registry.all())
```

The current `db_crud.py`, `spotify_control.py`, `memory_store.py` files inside `apps/mcp/spotify_mcp/` are deleted. Their bodies have moved to `packages/core/spotify_core/tools/`.

### 5.6 LangChain adapter (stub in this sub-project; consumed by C)

```python
# packages/core/spotify_core/tools/adapters/langchain_adapter.py
from langchain_core.tools import StructuredTool

def to_langchain_tools(specs: Iterable[ToolSpec]) -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            func=spec.func,
            name=spec.name,
            description=spec.description,
            args_schema=spec.args_schema,
        )
        for spec in specs
    ]
```

Sub-project A ships this adapter file with a passing unit test, but no agent consumes it yet. C wires it into the Chainlit agent.

## 6. Tools that need careful handling

- **`setup_check`** depends on `spotify_mcp.wizard.state.collect_report`, which lives in the MCP app. The function moves to `spotify_core.tools.diagnostics`; the underlying `collect_report` is also evaluated for migration to `spotify_core.setup`. If migration is too disruptive, the tool function keeps a deferred import from `spotify_mcp.wizard` — acceptable because `apps/mcp` is always installed when the MCP server runs, and the agent (which doesn't depend on `apps/mcp`) only needs `setup_check` if explicitly invoked.
- **Config helpers** (`DB_PATH`, `DEFAULT_USER_ID`, `EMPTY_DB_RESPONSE`, `TOKENS_DB`, `get_client_id`, `get_fernet_key`) currently live in `apps/mcp/spotify_mcp/config.py`. They need to move to (or be re-exported from) `spotify_core.config` because `spotify_core.tools` cannot import from `apps/mcp`. The user-facing `spotify-mcp` CLI continues to import them from wherever they end up.
- **`utils.to_error_response` and `utc_iso_to_local`** likewise move to `spotify_core.spotify_utils` (already exists).

These moves are mechanical but touch many call sites. They are explicitly **in scope** for this sub-project — without them the registry can't live in `packages/core`.

## 7. Migration strategy

Single PR (or stacked PRs of one tool category each, optional). Order:

1. Create `packages/core/spotify_core/tools/registry.py` (empty registry + decorator + ToolSpec).
2. Move config + utils from `apps/mcp/spotify_mcp/config.py` and `utils.py` into `spotify_core.config` / `spotify_core.spotify_utils`. Leave thin re-export shims in the MCP app so CLI imports keep working.
3. Port tools one category at a time (analytics → playback → memory → diagnostics). After each category:
   - Delete the corresponding `apps/mcp/spotify_mcp/*.py` file.
   - Update `_mcp.py` to use `attach_to_mcp(mcp, registry.by_category(...))`.
   - Run `uv run pytest` and a manual MCP smoke test (see §9).
4. Write the LangChain adapter and a unit test.
5. Delete dead code.

## 8. Test plan

### 8.1 Unit tests (new)

- `tests/test_tool_registry.py`
  - `@spotify_tool` populates the registry
  - `ToolSpec.args_schema` matches the function signature (Pydantic round-trip)
  - `to_langchain_tools` produces tools that, when `.invoke`'d with valid args, call the same underlying function
- `tests/test_tools_analytics.py`, `_playback.py`, `_memory.py`
  - Each tool function still passes its existing tests (most should be a rename/path change of current tests)

### 8.2 Adapter conformance test (new, critical)

`tests/test_mcp_adapter_conformance.py`: snapshot test that asserts the FastMCP tool registry after `attach_to_mcp` is **structurally identical** to the pre-refactor version. Use `mcp.list_tools()` (or FastMCP equivalent) and snapshot:
- ordered list of tool names
- each tool's input schema JSON
- each tool's annotations dict
- each tool's description string

This is the safety net that catches accidental schema drift.

### 8.3 Manual MCP smoke test

After the refactor, run:

```powershell
uv run python apps/mcp/server.py        # starts MCP over stdio
# In a separate terminal, run the MCP inspector
npx @modelcontextprotocol/inspector uv run --package spotify-analytics-mcp spotify-mcp serve
```

Then in the inspector:
1. Verify all ~15 tools appear with identical names + descriptions
2. Call `setup_check` — expect the same JSON shape as before
3. Call `get_listening_summary` against a populated DB — expect identical output
4. Call `get_top_artists` with `start_date`/`end_date` — expect identical filter behavior

If anything differs visibly, the refactor is incomplete.

## 9. Definition of done

- [ ] `packages/core/spotify_core/tools/` exists with `registry.py`, the four category modules, and both adapter files
- [ ] All ~15 tools are registered via `@spotify_tool` and the corresponding code in `apps/mcp/spotify_mcp/{db_crud,spotify_control,memory_store}.py` is deleted
- [ ] `apps/mcp/spotify_mcp/_mcp.py` consumes `registry` via `attach_to_mcp`
- [ ] Adapter conformance snapshot test passes (no schema drift)
- [ ] `uv run pytest` is green
- [ ] Manual MCP inspector smoke test verified on a populated local DB
- [ ] `MCP_QUICKSTART.md` requires no changes (proves the external interface is unchanged)
- [ ] `langchain_adapter.to_langchain_tools(registry.all())` returns 15 working `StructuredTool` instances with a basic invoke test

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| FastMCP's schema generation differs subtly from `pydantic.create_model` | Use FastMCP's own helper if exposed; otherwise verify via the conformance snapshot test (§8.2). If drift exists, narrow the registry to "store the raw func + Annotated signature" and let each adapter do its own schema synthesis. |
| Circular import: `spotify_core.tools` needs config, config needs… | Keep `spotify_core.config` free of imports from anywhere else in `spotify_core`. Tools import config, not the other way. |
| `setup_check`'s dependency on `spotify_mcp.wizard.state` | Either move `collect_report` to `spotify_core.setup`, or accept a deferred import inside the tool function. See §6. |
| `spotify-mcp` CLI breaks because config moved | Add re-export shims in `apps/mcp/spotify_mcp/config.py` for one release: `from spotify_core.config import DB_PATH, DEFAULT_USER_ID, ...`. |
| MCP playback tools rely on module-level state in `spotify_control` | None expected from a code scan — verify during port. If found, lift state to a small `PlaybackSession` class in `spotify_core.spotify_client`. |

## 11. Open questions

- Should `spotify_tool` accept an explicit `description` kwarg as override, or always read from `__doc__`? **Tentative: always docstring**, to keep one source of truth and avoid drift between MCP description and LangChain description.
- Should the registry be a true singleton, or passed explicitly? **Tentative: module-level singleton** for ergonomics — but exposed via `from spotify_core.tools import registry` rather than a global import side-effect that surprises tests.
- Async tools: do any of the current 15 need to be async? A quick scan suggests no (Spotify client is sync `httpx`). Deferred — registry can be extended later when an async tool actually appears.

These don't block starting implementation; pick the tentative answer if no objection during review.
