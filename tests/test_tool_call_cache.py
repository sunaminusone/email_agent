"""Tests for cross-group tool call cache: deduplication + observation sharing."""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.tool_call_cache import ToolCallCache
from src.common.execution_models import ExecutedToolCall
from src.tools.models import ToolRequest, ToolResult


def _make_call(
    tool_name: str,
    status: str = "ok",
    primary_records: list | None = None,
    structured_facts: dict | None = None,
) -> ExecutedToolCall:
    return ExecutedToolCall(
        call_id="c1",
        tool_name=tool_name,
        status=status,
        request=ToolRequest(tool_name=tool_name, query="test"),
        result=ToolResult(
            tool_name=tool_name,
            status=status,
            primary_records=primary_records or [],
            structured_facts=structured_facts or {},
        ),
    )


# --- Deduplication ---

def test_cache_miss_returns_none():
    cache = ToolCallCache()
    assert cache.get_cached("catalog_lookup_tool", "product", "CAR-T") is None


def test_cache_hit_after_store():
    cache = ToolCallCache()
    call = _make_call("catalog_lookup_tool")
    cache.store(call, "product", "CAR-T")

    cached = cache.get_cached("catalog_lookup_tool", "product", "CAR-T")
    assert cached is not None
    assert cached.tool_name == "catalog_lookup_tool"


def test_different_object_is_cache_miss():
    cache = ToolCallCache()
    call = _make_call("catalog_lookup_tool")
    cache.store(call, "product", "CAR-T")

    assert cache.get_cached("catalog_lookup_tool", "product", "CD3") is None


def test_different_tool_is_cache_miss():
    cache = ToolCallCache()
    call = _make_call("catalog_lookup_tool")
    cache.store(call, "product", "CAR-T")

    assert cache.get_cached("technical_rag_tool", "product", "CAR-T") is None


# --- Observation extraction ---

def test_extracts_product_name_from_primary_records():
    cache = ToolCallCache()
    call = _make_call(
        "catalog_lookup_tool",
        primary_records=[{"display_name": "CD3 Antibody", "business_line": "reagents"}],
    )
    cache.store(call, "product", "CD3")

    assert cache.discovered_product_name == "CD3 Antibody"
    assert cache.discovered_business_line == "reagents"


def test_extracts_service_name_from_structured_facts():
    cache = ToolCallCache()
    call = _make_call(
        "technical_rag_tool",
        structured_facts={"service_name": "CAR-T Cell Design", "business_line": "car_t_car_nk"},
    )
    cache.store(call, "service", "CAR-T")

    assert cache.discovered_service_name == "CAR-T Cell Design"
    assert cache.discovered_business_line == "car_t_car_nk"


def test_first_observation_wins():
    """First group's discovery takes precedence."""
    cache = ToolCallCache()
    call1 = _make_call("catalog_lookup_tool", primary_records=[{"display_name": "CD3 Antibody"}])
    call2 = _make_call("catalog_lookup_tool", primary_records=[{"display_name": "CD19 Antibody"}])

    cache.store(call1, "product", "CD3")
    cache.store(call2, "product", "CD19")

    assert cache.discovered_product_name == "CD3 Antibody"


def test_no_observations_from_error():
    cache = ToolCallCache()
    call = _make_call("catalog_lookup_tool", status="error", primary_records=[{"display_name": "X"}])
    cache.store(call, "product", "X")

    assert cache.discovered_product_name == ""


def test_observations_dict():
    cache = ToolCallCache()
    call = _make_call(
        "catalog_lookup_tool",
        primary_records=[{"display_name": "CD3", "business_line": "reagents"}],
    )
    cache.store(call, "product", "CD3")

    obs = cache.observations
    assert "product_name" in obs
    assert "business_line" in obs
