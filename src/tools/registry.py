from __future__ import annotations

from collections.abc import Iterable

from src.tools.contracts import RegistryEntry, ToolExecutor
from src.tools.errors import ToolRegistrationError, UnknownToolError
from src.tools.models import ToolCapability


_REGISTRY: dict[str, RegistryEntry] = {}


def register_tool(
    *,
    tool_name: str,
    executor: ToolExecutor,
    capability: ToolCapability | None = None,
    family: str = "",
    description: str = "",
    tags: Iterable[str] = (),
    replace: bool = False,
) -> RegistryEntry:
    if not tool_name:
        raise ToolRegistrationError("tool_name must be non-empty.")
    if tool_name in _REGISTRY and not replace:
        raise ToolRegistrationError(f"Tool '{tool_name}' is already registered.")

    entry = RegistryEntry(
        tool_name=tool_name,
        executor=executor,
        capability=capability,
        family=family,
        description=description,
        tags=tuple(tags),
    )
    _REGISTRY[tool_name] = entry
    return entry


def get_registry_entry(tool_name: str) -> RegistryEntry:
    try:
        return _REGISTRY[tool_name]
    except KeyError as exc:
        raise UnknownToolError(f"Tool '{tool_name}' is not registered.") from exc


def get_tool_executor(tool_name: str) -> ToolExecutor:
    return get_registry_entry(tool_name).executor


def get_tool_capability(tool_name: str) -> ToolCapability | None:
    return get_registry_entry(tool_name).capability


def has_tool(tool_name: str) -> bool:
    return tool_name in _REGISTRY


def list_registry_entries() -> list[RegistryEntry]:
    return list(_REGISTRY.values())


def list_tool_names() -> list[str]:
    return list(_REGISTRY.keys())


def clear_registry() -> None:
    _REGISTRY.clear()
