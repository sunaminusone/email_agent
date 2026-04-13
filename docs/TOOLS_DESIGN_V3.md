# Tools Design v3

## Purpose

The tools module provides the system's external capabilities — querying product catalogs, retrieving technical documents, looking up orders, etc. Each tool is a self-contained unit that:
1. **Declares** what it can do (`ToolCapability`)
2. **Accepts** a structured request (`ToolRequest`)
3. **Returns** a structured result (`ToolResult`)

In v3, tools become **self-describing**: instead of relying on hardcoded mappings in routing or the executor, each tool declares enough information for the executor to autonomously decide when to use it.

### What changes in v3

The tools module itself does not undergo a major rewrite. The infrastructure (registry, dispatcher, executor protocol, request mappers) is already well-structured. The change is:

1. **Enriched ToolCapability** — add 3 fields so tools self-describe for the executor
2. **Updated capability declarations** — each tool provides richer metadata
3. **v3 dialogue act compatibility** — capabilities accept both v2 uppercase and v3 lowercase acts

### What does NOT change

- Tool implementations (product_tool.py, order_tool.py, etc.)
- Registry infrastructure (register_tool, list_registry_entries, etc.)
- Dispatcher (safe_dispatch_tool)
- ToolRequest and ToolResult contracts
- Request mappers (request_mapper.py files)
- Result builders (ok_result, error_result, etc.)

## Current State Analysis

### What exists (`src/tools/`)

| File | Role | v3 status |
| --- | --- | --- |
| `models.py` | ToolCapability, ToolRequest, ToolResult, ToolConstraints | **Enrich** — add 3 fields to ToolCapability |
| `contracts.py` | ToolExecutor protocol, RegistryEntry dataclass | **Unchanged** |
| `registry.py` | register_tool(), list_registry_entries(), get_tool_capability() | **Unchanged** |
| `dispatcher.py` | safe_dispatch_tool() with error handling | **Unchanged** |
| `base.py` | BaseTool class with capability property | **Unchanged** |
| `types.py` | ToolStatus, ToolFamily literals | **Unchanged** |
| `result_builders.py` | ok_result(), error_result(), etc. | **Unchanged** |
| `errors.py` | ToolError hierarchy | **Unchanged** |
| `catalog/capability.py` | CATALOG_LOOKUP, PRICING_LOOKUP capabilities | **Enrich** — add description, request_flags, params |
| `rag/capability.py` | TECHNICAL_RAG capability | **Enrich** |
| `quickbooks/capability.py` | ORDER, INVOICE, SHIPPING, CUSTOMER capabilities | **Enrich** |
| `documents/capability.py` | DOCUMENT_LOOKUP capability | **Enrich** |
| `*/request_mapper.py` | Build tool-specific params from ToolRequest | **Unchanged** |
| `*/*_tool.py` | Tool implementations | **Unchanged** |

### What works well

1. **Registry pattern** — `register_tool()` and `list_registry_entries()` already provide the discovery mechanism the v3 executor needs. No new infrastructure required.

2. **Capability-per-tool** — each tool family already has a `capability.py` declaring a `ToolCapability` object. The pattern is established; we just enrich the data.

3. **ToolExecutor protocol** — the `__call__(request: ToolRequest) -> ToolResult` contract is clean. Tools are callable, testable, and registry-compatible.

4. **Separation of concerns** — request_mapper builds params, the tool executes, result_builders format output. Each concern is isolated.

### What's insufficient for v3

1. **ToolCapability lacks description.** The v3 executor's Level 2 LLM needs to understand what each tool does in natural language. Current capability only has `tool_name` — the LLM can't reason about "should I use catalog_lookup_tool or technical_rag_tool for a competitor product alternative?"

2. **Request flag mapping is hardcoded in the executor.** The executor design has `_FLAG_BOOST = {"needs_price": "pricing_lookup_tool", ...}`. Adding a new tool means editing the executor. With self-describing tools, each tool should declare which request_flags it serves.

3. **No required_params declaration.** The executor doesn't know what a tool needs to execute. If a tool requires `catalog_number` but the executor only has `product_name`, it can't predict whether the request will succeed or fail.

4. **supported_dialogue_acts uses v2 uppercase only.** v3 uses lowercase acts (`inquiry`, `selection`, `closing`). Capabilities need to accept both during migration.

## v3 Design

### Enriched ToolCapability

```python
class ToolCapability(_ToolModel):
    tool_name: str

    # NEW: human-readable description for Level 2 LLM reasoning
    description: str = ""

    # Existing: what this tool supports (used by executor scoring)
    supported_object_types: list[ObjectType] = Field(default_factory=list)
    supported_dialogue_acts: list[str] = Field(default_factory=list)
    supported_modalities: list[str] = Field(default_factory=list)

    # NEW: which ingestion request_flags this tool can serve
    # Replaces executor's hardcoded _FLAG_BOOST mapping
    supported_request_flags: list[str] = Field(default_factory=list)

    # NEW: parameters the tool needs to execute meaningfully
    required_params: list[str] = Field(default_factory=list)

    # Existing: execution characteristics
    can_run_in_parallel: bool = False
    returns_structured_facts: bool = False
    returns_unstructured_snippets: bool = False
    requires_external_system: bool = False
```

### Field details

**`description`**

A 1-2 sentence description of what the tool does. Used in the Level 2 LLM prompt:

```
Available tools (from registry):
- catalog_lookup_tool: 查询产品目录，返回产品规格、型号、应用场景等结构化信息
- technical_rag_tool: 检索技术文档知识库，返回实验方案、产品使用指南等非结构化内容
- order_lookup_tool: 查询 QuickBooks 订单系统，返回订单状态、金额、发货信息
```

Without descriptions, the LLM only sees tool names and must guess what they do.

**`supported_request_flags`**

Maps ingestion `ParserRequestFlags` to tools. Each flag name corresponds to a boolean field in `ParserRequestFlags`:

```python
# ParserRequestFlags fields (from ingestion):
needs_price, needs_timeline, needs_protocol, needs_customization,
needs_order_status, needs_shipping_info, needs_documentation,
needs_troubleshooting, needs_quote, needs_availability,
needs_recommendation, needs_comparison, needs_invoice,
needs_refund_or_cancellation, needs_sample, needs_regulatory_info
```

Each tool declares which flags it handles. The executor scoring function becomes:

```python
# Before (hardcoded in executor):
_FLAG_BOOST = {
    "needs_price":    "pricing_lookup_tool",
    "needs_protocol": "technical_rag_tool",
}

# After (self-describing):
if context.request_flags:
    for flag_name in capability.supported_request_flags:
        if getattr(context.request_flags, flag_name, False):
            score += 0.2
```

Adding a new tool no longer requires editing the executor.

**`required_params`**

Lists parameter names the tool needs to produce meaningful results. This helps the executor:
- Determine if it has enough information to build a request
- Decide whether to skip a tool when required data is missing
- Generate better clarification prompts (via routing feedback)

Values are semantic names matching what the request_mapper expects:

```python
required_params=["object_type"]              # catalog: needs to know what to search
required_params=["order_number"]             # order: must have an order ID
required_params=[]                           # rag: can search with just a query
```

### Updated Capability Declarations

#### catalog/capability.py

```python
CATALOG_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="catalog_lookup_tool",
    description="查询产品目录，返回产品规格、型号、应用场景、存储条件等结构化信息",
    supported_object_types=["product", "service"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "ELABORATE", "inquiry", "selection"],
    supported_modalities=["structured_lookup", "hybrid"],
    supported_request_flags=["needs_availability", "needs_comparison", "needs_sample"],
    required_params=["object_type"],
    returns_structured_facts=True,
)

PRICING_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="pricing_lookup_tool",
    description="查询产品定价信息，返回单价、批量折扣、报价有效期等",
    supported_object_types=["product", "service"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "inquiry", "selection"],
    supported_modalities=["structured_lookup", "hybrid"],
    supported_request_flags=["needs_price", "needs_quote"],
    required_params=["object_type"],
    returns_structured_facts=True,
)
```

#### rag/capability.py

```python
TECHNICAL_RAG_CAPABILITY = ToolCapability(
    tool_name="technical_rag_tool",
    description="检索技术文档知识库，返回实验方案、使用指南、故障排查等非结构化技术内容",
    supported_object_types=["service", "product", "scientific_target"],
    supported_dialogue_acts=["INQUIRY", "ELABORATE", "SELECTION", "inquiry", "selection"],
    supported_modalities=["unstructured_retrieval", "hybrid"],
    supported_request_flags=[
        "needs_protocol", "needs_troubleshooting", "needs_recommendation",
        "needs_regulatory_info",
    ],
    required_params=[],
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
```

#### documents/capability.py

```python
DOCUMENT_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="document_lookup_tool",
    description="查询文档管理系统，返回数据表、使用手册、技术文档等文件引用",
    supported_object_types=["document", "product", "service"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "ELABORATE", "inquiry", "selection"],
    supported_modalities=["structured_lookup", "unstructured_retrieval", "hybrid"],
    supported_request_flags=["needs_documentation"],
    required_params=[],
    can_run_in_parallel=True,
    returns_structured_facts=True,
    returns_unstructured_snippets=True,
)
```

#### quickbooks/capability.py

```python
CUSTOMER_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="customer_lookup_tool",
    description="查询 QuickBooks 客户信息，返回客户名称、联系方式、历史交易摘要",
    supported_object_types=["customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=[],
    required_params=["customer_identifier"],
    returns_structured_facts=True,
    requires_external_system=True,
)

INVOICE_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="invoice_lookup_tool",
    description="查询 QuickBooks 发票信息，返回发票金额、状态、明细行项目",
    supported_object_types=["invoice", "order", "customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_invoice"],
    required_params=[],
    returns_structured_facts=True,
    requires_external_system=True,
)

ORDER_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="order_lookup_tool",
    description="查询 QuickBooks 订单状态，返回订单详情、付款状态、预计交付时间",
    supported_object_types=["order", "customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_order_status", "needs_timeline"],
    required_params=[],
    returns_structured_facts=True,
    requires_external_system=True,
)

SHIPPING_LOOKUP_CAPABILITY = ToolCapability(
    tool_name="shipping_lookup_tool",
    description="查询物流配送信息，返回快递单号、配送状态、预计送达时间",
    supported_object_types=["shipment", "order", "customer"],
    supported_dialogue_acts=["INQUIRY", "SELECTION", "inquiry", "selection"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_shipping_info"],
    required_params=[],
    can_run_in_parallel=True,
    returns_structured_facts=True,
    requires_external_system=True,
)
```

### How the Executor Uses Enriched Capabilities

#### Tool selection scoring (Level 1)

```python
def _score_tool(capability: ToolCapability, context: ExecutionContext) -> float:
    score = 0.0

    # Object type match (0.4)
    if context.primary_object and context.primary_object.object_type in capability.supported_object_types:
        score += 0.4
    for obj in context.secondary_objects:
        if obj.object_type in capability.supported_object_types:
            score += 0.1

    # Dialogue act match (0.3)
    if context.dialogue_act.act in capability.supported_dialogue_acts:
        score += 0.3

    # Retrieval needs match (0.15 each)
    retrieval_needs = _derive_retrieval_needs(context.request_flags, context.primary_object)
    for need in retrieval_needs:
        if need in capability.supported_modalities:
            score += 0.15

    # Request flags boost (0.2 each) -- reads from tool's self-description
    if context.request_flags:
        for flag_name in capability.supported_request_flags:
            if getattr(context.request_flags, flag_name, False):
                score += 0.2

    # Retrieval hints boost (0.15)
    if context.retrieval_hints and capability.tool_name in (context.retrieval_hints.suggested_tools or []):
        score += 0.15

    return score
```

No hardcoded `_FLAG_BOOST` dictionary. The scoring function reads directly from each tool's `supported_request_flags`.

#### LLM tool selection (Level 2)

The Level 2 prompt includes tool descriptions:

```
Available tools:
- catalog_lookup_tool: 查询产品目录，返回产品规格、型号、应用场景、存储条件等结构化信息
  Supports: product, service | structured_lookup, hybrid
  Request flags: needs_availability, needs_comparison, needs_sample

- technical_rag_tool: 检索技术文档知识库，返回实验方案、使用指南、故障排查等非结构化技术内容
  Supports: service, product, scientific_target | unstructured_retrieval, hybrid
  Request flags: needs_protocol, needs_troubleshooting, needs_recommendation

- order_lookup_tool: 查询 QuickBooks 订单状态，返回订单详情、付款状态、预计交付时间
  Supports: order, customer | external_api
  Request flags: needs_order_status, needs_timeline
```

This gives the LLM enough context to reason about which tool to use for novel queries like "Do you have a Lipofectamine alternative?"

### Adding a New Tool: The v3 Experience

To add an `inventory_tool` that checks real-time stock levels:

**Step 1**: Create the tool implementation and capability:

```python
# src/tools/inventory/capability.py
INVENTORY_CAPABILITY = ToolCapability(
    tool_name="inventory_tool",
    description="查询实时库存水平，返回当前库存量、预计补货时间、仓库位置",
    supported_object_types=["product"],
    supported_dialogue_acts=["INQUIRY", "inquiry"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_availability", "needs_timeline"],
    required_params=["object_type"],
    returns_structured_facts=True,
    requires_external_system=True,
)
```

**Step 2**: Register the tool:

```python
# src/tools/inventory/__init__.py
register_tool(
    tool_name="inventory_tool",
    executor=InventoryTool(),
    capability=INVENTORY_CAPABILITY,
    family="inventory",
)
```

**Done.** No changes to:
- Routing (doesn't know about tools)
- Executor (reads capabilities from registry)
- _FLAG_BOOST (doesn't exist anymore)
- planner_rules (deleted in v3)

The executor discovers the new tool through `list_registry_entries()`, sees it supports `needs_availability`, and selects it when a customer asks about product stock.

## Data Contracts

### ToolCapability (enriched)

```python
class ToolCapability(_ToolModel):
    tool_name: str
    description: str = ""
    supported_object_types: list[ObjectType] = Field(default_factory=list)
    supported_dialogue_acts: list[str] = Field(default_factory=list)
    supported_modalities: list[str] = Field(default_factory=list)
    supported_request_flags: list[str] = Field(default_factory=list)
    required_params: list[str] = Field(default_factory=list)
    can_run_in_parallel: bool = False
    returns_structured_facts: bool = False
    returns_unstructured_snippets: bool = False
    requires_external_system: bool = False
```

### ToolRequest (unchanged for now)

```python
class ToolRequest(_ToolModel):
    tool_name: str
    query: str = ""
    primary_object: ObjectCandidate | None = None
    secondary_objects: list[ObjectCandidate] = Field(default_factory=list)
    dialogue_act: DialogueActResult = Field(default_factory=DialogueActResult)
    modality_decision: ModalityDecision = Field(default_factory=ModalityDecision)
    constraints: ToolConstraints = Field(default_factory=ToolConstraints)
```

Note: `modality_decision` is kept for v2 compatibility. In v3, the executor will not populate it (uses default). Full removal happens when all request_mappers are verified to not depend on it.

### ToolResult (unchanged)

```python
class ToolResult(_ToolModel):
    tool_name: str
    status: str = "empty"          # ok | partial | empty | error
    primary_records: list[dict]
    supporting_records: list[dict]
    structured_facts: dict
    unstructured_snippets: list[dict]
    artifacts: list[dict]
    errors: list[str]
    debug_info: dict
```

### Registry contracts (unchanged)

```python
class ToolExecutor(Protocol):
    def __call__(self, request: ToolRequest) -> ToolResult: ...

@dataclass
class RegistryEntry:
    tool_name: str
    executor: ToolExecutor
    capability: ToolCapability | None = None
    family: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
```

## Target File Structure

```
src/tools/                              # No structural changes
+-- __init__.py                         # Unchanged
+-- models.py                           # ToolCapability enriched (3 new fields)
+-- contracts.py                        # Unchanged
+-- registry.py                         # Unchanged
+-- dispatcher.py                       # Unchanged
+-- base.py                             # Unchanged
+-- types.py                            # Unchanged
+-- result_builders.py                  # Unchanged
+-- errors.py                           # Unchanged
+-- catalog/
|   +-- capability.py                   # Enriched declarations
|   +-- product_tool.py                 # Unchanged
|   +-- pricing_tool.py                 # Unchanged
|   +-- request_mapper.py              # Unchanged
+-- rag/
|   +-- capability.py                   # Enriched
|   +-- technical_tool.py              # Unchanged
|   +-- request_mapper.py              # Unchanged
+-- documents/
|   +-- capability.py                   # Enriched
|   +-- documentation_tool.py          # Unchanged
|   +-- request_mapper.py              # Unchanged
+-- quickbooks/
    +-- capability.py                   # Enriched
    +-- order_tool.py                   # Unchanged
    +-- invoice_tool.py                 # Unchanged
    +-- shipping_tool.py               # Unchanged
    +-- customer_tool.py               # Unchanged
    +-- request_mapper.py              # Unchanged
    +-- base.py                         # Unchanged
    +-- filters.py                      # Unchanged
```

## Migration Steps

### Step 1: Enrich ToolCapability model (zero risk)

1. Add `description`, `supported_request_flags`, `required_params` to `ToolCapability` in `models.py`
2. All new fields have default values — existing code is unaffected
3. `supported_dialogue_acts` type changed from `list[DialogueActType]` to `list[str]` to accept both v2 and v3 acts

### Step 2: Update capability declarations (zero risk)

1. Add descriptions, request_flags, and required_params to each capability.py
2. Add v3 lowercase dialogue acts alongside v2 uppercase acts
3. No behavioral change — capabilities are richer but the v2 executor doesn't read the new fields

### Step 3: Executor uses new fields (when executor migrates)

1. Executor's `_score_tool()` reads `supported_request_flags` instead of hardcoded `_FLAG_BOOST`
2. Executor's Level 2 prompt includes `description` for each tool
3. Delete `_FLAG_BOOST` dictionary from executor

## Integration With Other Modules

### Tools reads from

| Module | What tools reads | Why |
| --- | --- | --- |
| **Executor** | `ToolRequest` (query, object, constraints) | Input to tool execution |

### Modules that read from tools

| Module | What it reads | Why |
| --- | --- | --- |
| **Executor** | `ToolCapability` via `list_registry_entries()` | Tool selection scoring |
| **Executor** | `ToolResult` via `safe_dispatch_tool()` | Process execution results |

### Modules that do NOT interact with tools

| Module | Why not |
| --- | --- |
| **Routing** | v3 routing does not select tools or read capabilities |
| **Ingestion** | Ingestion parses the query; it doesn't know about tools |
| **Objects** | Object resolution is independent of tool capabilities |
| **Responser** | Responser reads executor results, not tool results directly |

## Anti-Patterns

1. **Tools that decide what other tools to call.** Each tool returns data, not instructions. The executor alone decides the next action based on tool results.

2. **Tool-specific logic in the executor.** If the executor has `if tool_name == "catalog_lookup_tool": ...`, the architecture is wrong. Use `ToolCapability` fields to make decisions generically.

3. **Request flags mapped in the executor.** If `_FLAG_BOOST = {"needs_price": "pricing_tool"}` exists in the executor, it belongs in `ToolCapability.supported_request_flags` instead.

4. **Routing importing from tools.** Routing should never import `src.tools`. Tool selection is the executor's responsibility.

5. **Overly broad supported_request_flags.** A tool should only declare flags it can actually fulfill. Don't add `needs_recommendation` to `catalog_lookup_tool` just because the catalog has product data — unless the tool's implementation actually provides recommendation-quality results.
