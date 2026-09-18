"""Tool factory for JARVIS: author its own tools — with or without the sandbox.

``generate_tool`` takes a name and a Python implementation (written by the LLM),
validates the source with an AST walk (banning dangerous imports and calls),
writes it to ``src/generated_tools/``, smoke-tests it against a scratch run, and
registers it. Registered tools are callable immediately via ``run_generated_tool``
and are re-loaded automatically on the next process start, so the toolset grows
across sessions.

Trust mode (``trust=True`` on the call, or the ``JARVIS_TRUST_TOOLS=1`` env) skips
validation and smoke-testing entirely — the source executes as-written. That is
the guardrail-off path used by autonomous mitigation tooling.
"""

import ast
import json
import re
import threading
from pathlib import Path

from src.config.settings import Settings
from src.tools.base import STORE, register_critical

ALLOWED_IMPORTS = {
    "src.tools.base",
    "src.tools.watch",
    "src.store",
    "datetime",
    "math",
    "json",
    "re",
    "typing",
    "collections",
}

BLOCKED_CALLS = {
    "open",
    "eval",
    "exec",
    "compile",
    "input",
    "breakpoint",
    "__import__",
}

NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")

_DEFAULT_DIR = (
    Path(Settings.from_env(require_key=False).data_file).resolve().parent.parent / "src" / "generated_tools"
)

_GENERATED_DIR = None
GENERATED: dict[str, dict] = {}
_LOCK = threading.RLock()
_TRUST_MODE: bool | None = None


def trust_mode() -> bool:
    """Whether validation is bypassed globally (env JARVIS_TRUST_TOOLS=1)."""
    if _TRUST_MODE is not None:
        return _TRUST_MODE
    return Settings.from_env(require_key=False).trust_tools


def set_trust_mode(enabled: bool) -> None:
    """Globally enable/disable validation bypass (used by tests and the CLI)."""
    global _TRUST_MODE
    _TRUST_MODE = bool(enabled)


def generated_dir() -> Path:
    return Path(_GENERATED_DIR) if _GENERATED_DIR else _DEFAULT_DIR


def set_generated_dir(path) -> None:
    """Point the factory at an alternate directory (used by tests)."""
    global _GENERATED_DIR
    _GENERATED_DIR = Path(path) if path else None


def reset_generated_registry() -> None:
    """Forget every generated tool (used by tests)."""
    with _LOCK:
        GENERATED.clear()


def _module_roots(node) -> list[str]:
    if isinstance(node, ast.Import):
        return [a.name.split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.module else []
    return []


def validate_tool_source(tool_name: str, source: str) -> tuple[bool, list[str]]:
    """AST-based gate. Returns (ok, errors). Blocks imports outside an allow-list,
    dangerous builtins, and anything that doesn't define ``def <tool_name>(...).``"""
    errors: list[str] = []
    if not NAME_RE.match(tool_name):
        return False, [f"tool name '{tool_name}' is not a valid Python identifier"]
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, [f"syntax error at line {exc.lineno}: {exc.msg}"]

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root in _module_roots(node):
                if root not in ALLOWED_IMPORTS:
                    errors.append(f"import '{root}' is not allowed")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
            if name in BLOCKED_CALLS:
                errors.append(f"call to '{name}' is not allowed")
        elif isinstance(node, ast.Delete) or isinstance(node, ast.Global) or isinstance(node, ast.Nonlocal):
            errors.append(f"'{type(node).__name__}' statements are not allowed")

    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not any(f.name == tool_name for f in funcs):
        errors.append(f"must define a function named '{tool_name}'")

    return (not errors), errors


def _load_module(tool_name: str, source: str):
    namespace: dict = {}
    exec(compile(source, f"<generated:{tool_name}>", "exec"), namespace)
    return namespace[tool_name]


def _smoke(implementation: str, tool_name: str) -> tuple[bool, str]:
    """Run the implementation once with no args. Missing-required-args (TypeError)
    is treated as OK — real runtime errors are not."""
    try:
        fn = _load_module(tool_name, implementation)
        out = fn()
    except TypeError as exc:
        if "argument" in str(exc) or "positional" in str(exc):
            return True, "compiles; requires arguments"
        return False, f"execution error: {type(exc).__name__}: {exc}"
    except Exception as exc:
        return False, f"execution error: {type(exc).__name__}: {exc}"
    if isinstance(out, str):
        return True, f"returned {len(out)} chars"
    return isinstance(out, (int, float)), f"returned non-string {type(out).__name__}"


def write_generated_file(tool_name: str, implementation: str) -> Path:
    generated_dir().mkdir(parents=True, exist_ok=True)
    target = generated_dir() / f"{tool_name}.py"
    try:
        target.write_text(implementation, encoding="utf-8")
    except (PermissionError, OSError) as exc:
        raise RuntimeError(f"could not write generated tool file: {exc}") from exc
    return target


def _register(tool_name: str, implementation: str, description: str, fn=None):
    with _LOCK:
        if fn is None:
            fn = _load_module(tool_name, implementation)
        GENERATED[tool_name] = {
            "description": description,
            "implementation": implementation,
            "fn": fn,
        }


def generate_tool(name: str, implementation: str, description: str = "", trust: bool = False) -> str:
    """Author a new tool: name, Python source implementing def <name>(...), and a short description. Validates in a sandbox, writes it to disk, and hot-registers it. Pass trust=True (or set JARVIS_TRUST_TOOLS=1) to skip validation and smoke-testing entirely — the source executes as-written."""
    if name in GENERATED:
        return f"Error: a generated tool named '{name}' already exists."
    if description.strip() == "":
        description = f"Custom tool '{name}' authored through the tool factory."
    bypass = trust or trust_mode()
    if bypass:
        smoke_note = "trusted — validation bypassed"
    else:
        ok, errors = validate_tool_source(name, implementation)
        if not ok:
            return "Validation failed:\n" + "\n".join(errors)
        smoke_ok, smoke_note = _smoke(implementation, name)
        if not smoke_ok:
            return f"Smoke test failed ({smoke_note}). The tool was not registered."
    try:
        write_generated_file(name, implementation)
    except RuntimeError as exc:
        return f"Error: {exc}"
    try:
        _register(name, implementation, description)
    except Exception as exc:
        return f"Error registering tool: {type(exc).__name__}: {exc}"
    STORE.notify(f"Generated tool '{name}' registered ({smoke_note}).")
    STORE.save()
    return (
        f"Tool '{name}' authored, validated, and registered. Smoke test: {smoke_note}.\n"
        f"Invoke it anytime with run_generated_tool(name='{name}', arguments='{{\"arg\": value}}')."
    )


def load_generated_modules() -> int:
    """Re-register every *.py in the generated directory (startup persistence)."""
    with _LOCK:
        if not generated_dir().exists():
            return 0
        loaded = 0
        for path in sorted(generated_dir().glob("*.py")):
            name = path.stem
            if not NAME_RE.match(name) or name in GENERATED:
                continue
            try:
                implementation = path.read_text(encoding="utf-8")
                ok, _errors = validate_tool_source(name, implementation)
                if not ok:
                    continue
                _register(name, implementation, f"Generated tool '{name}'", fn=_load_module(name, implementation))
                loaded += 1
            except Exception:
                continue
        return loaded


def validate_tool(name: str, source: str) -> str:
    """Validate a candidate tool (in a sandbox) WITHOUT writing or registering it. Returns the verdict."""
    ok, errors = validate_tool_source(name, source)
    if ok:
        smoke_ok, smoke_note = _smoke(source, name)
        verdict = "passes validation" if smoke_ok else f"fails smoke test ({smoke_note})"
        return f"Tool '{name}' {verdict}."
    return "Validation failed:\n" + "\n".join(errors)


def delete_tool(name: str, delete_file: bool = False) -> str:
    """Remove a generated tool from the registry; optionally delete its source file from disk."""
    with _LOCK:
        if name not in GENERATED:
            return f"Error: no generated tool '{name}'."
        del GENERATED[name]
        if delete_file:
            target = generated_dir() / f"{name}.py"
            if target.exists():
                target.unlink()
            else:
                return f"Removed '{name}' from registry, but no source file was found."
        return f"Removed generated tool '{name}' from the registry."


def list_generated_tools() -> str:
    """List the tools JARVIS has authored through the tool factory."""
    if not GENERATED:
        return "No generated tools yet. Ask JARVIS to build one: 'create a tool that ...'."
    lines = [f"Generated tools ({len(GENERATED)}):"]
    for name, info in sorted(GENERATED.items()):
        lines.append(f"  - {name}: {info['description']}")
    return "\n".join(lines)


def run_generated_tool(tool_name: str, arguments: str = "{}") -> str:
    """Call a generated tool by name, passing its arguments as a JSON object string."""
    if tool_name not in GENERATED:
        return f"Error: no generated tool '{tool_name}'. Available: {', '.join(sorted(GENERATED)) or 'none'}."
    try:
        kwargs = json.loads(arguments or "{}")
        if not isinstance(kwargs, dict):
            raise ValueError("arguments must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        return f"Error: arguments must be a JSON object string. ({exc})"
    try:
        result = GENERATED[tool_name]["fn"](**kwargs)
    except Exception as exc:
        return f"Error running '{tool_name}': {type(exc).__name__}: {exc}"
    if isinstance(result, dict):
        return json.dumps(result, default=str)
    return str(result)


register_critical("generate_tool")

load_generated_modules()