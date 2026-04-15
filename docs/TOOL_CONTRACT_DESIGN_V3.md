# Tool Readiness & Three-Layer Execution Design

## 定位

这是一个基于检索与业务查询、以就绪度判断驱动执行的智能客服 Agent。

- **60%** 技术咨询 → RAG 检索（永远就绪，无参数依赖）
- **40%** 产品/订单咨询 → QuickBooks 查询（需要一个 identifier）

不是开放世界的规划系统。所有复杂度必须与这个规模匹配。

---

## 动机

当前系统的 clarification 判断基于硬编码的静态字典：

```python
# src/routing/policies/clarification.py
_CRITICAL_FIELDS = {
    "order":    {"order_number", "customer_identifier"},
    "invoice":  {"invoice_number", "customer_identifier"},
    "shipment": {"order_number", "tracking_number"},
}
```

这些硬编码有三个根本性问题：

1. **时机错了**。clarification 发生在 routing 阶段（tool selection 之前）。但"缺什么"只有知道"走哪条路"之后才有意义。
2. **判断者错了**。routing policy 通过查表来判断 tool 能不能跑，但只有 tool 自己最清楚自己需要什么。
3. **粒度错了**。按 object_type 聚合所有 tool 的需求，得到的是"最大公约数"。

### 改动目标

| 维度 | 现在 | 目标 |
| --- | --- | --- |
| "缺什么"的判断者 | routing policy 查静态表 | tool 自己声明 |
| clarify 的时机 | routing 阶段（tool selection 之前） | path evaluation 之后（tool 已选定） |
| 加新 tool 的成本 | 改 tool + 改 `_CRITICAL_FIELDS` + 改 `relevant_prefixes` | 只改 tool（声明 identifiers） |

### 设计原则

1. **Tool 是自己需求的唯一权威。** 系统中不应存在任何"代表 tool 说它需要什么"的外部表。
2. **Clarification 是最后手段。** 能执行就执行，能补全就补全，不到万不得已不追问。
3. **简单胜于通用。** 5 个工具 + 1 条 resolution 路径不需要通用的 contract evaluation engine。

---

## 三层执行模型

系统的执行策略分为三层，每一层解决一个清晰的问题：

```
第一层：Primary Plan     — 选什么工具？
第二层：Readiness Plan   — 工具能跑吗？
第三层：Resolution Plan  — 跑不了怎么补？
```

### 第一层：Primary Plan（主工具选择）

根据 intent 选最可能直接解决问题的主工具。不是复杂 planning，就是 primary tool selection：

| Intent | Primary Tool |
| --- | --- |
| technical_question | technical_rag_tool |
| product_inquiry | catalog_lookup_tool |
| pricing_question | pricing_lookup_tool |
| order_status | order_lookup_tool |
| shipping_status | shipping_lookup_tool |
| invoice_question | invoice_lookup_tool |

这一层由现有的 `tool_selector.select_tools()` 实现，不需要改动。

### 第二层：Readiness Plan（就绪度判断）

对主工具做 readiness 判断。这是系统最关键的 plan — 不是计划"做什么任务"，而是判断"主任务能不能直接执行"。

判断基于工具声明的 identifiers：

```
有 full identifier？  → full，直接执行
有 degraded identifier？→ degraded，带说明执行（结果可能不唯一）
都没有？              → insufficient，进入第三层
```

**full vs degraded 的语义：标识符精度**

- **full**: 精确标识符，API 返回唯一结果（如 order_number → 一条订单）
- **degraded**: 模糊标识符，API 可能返回多条结果（如 customer_name → 多条订单）

这不是"参数组部分满足"的数学问题，而是 **结果精度** 的业务语义。

### 第三层：Resolution Plan（一步补全）

如果主工具跑不了，只允许做 **一层 provider-based resolution**：

```
主工具缺 customer_name
→ 看有没有别的 tool 能提供 customer_name
→ 有的话先跑 provider tool（provider 必须自身 full）
→ 再回到主工具
→ 还是不行？→ clarify
```

约束：
1. **只允许一层 resolution**（不递归）
2. **Provider 自身必须 full**（不允许 degraded provider）
3. **Resolution 失败 → 直接 clarify**，不再尝试其他路径

### 完整流程

```
Primary tool selection
  → readiness check
    → full?     → execute
    → degraded? → execute (带说明)
    → insufficient?
        → find provider (one-step)
            → provider found & full? → run provider → re-check primary → execute or clarify
            → no provider?           → clarify
```

---

## 行为准则：Clarification 只在真正阻塞时触发

```
能执行就不要问
  → 能从 context 补全就不要问
    → 能先跑 provider 补全就不要问
      → 只有真的被阻塞了才问
```

### 场景演练

**用户说：** "Where is my order?"

**context：** `email: abc@example.com`

**当前系统（错误行为）：**
1. routing 查 `_CRITICAL_FIELDS["order"]` → 缺 order_number、customer_identifier
2. 立即 clarify："Please provide your order number."

**新系统（正确行为）：**
1. tool_selector → order_lookup_tool
2. readiness check → insufficient（缺 order_number / customer_name / customer_identifier）
3. resolution plan → customer_lookup_tool 能跑（email 满足 customer_identifier）→ 提供 customer_name
4. 重新评估 order_lookup_tool → degraded（customer_name 是模糊标识符）→ 执行
5. 返回订单列表，零次 clarification

---

## 数据模型

### ToolCapability 的 readiness 字段

```python
class ToolCapability(_ToolModel):
    # ... 所有现有字段不变 ...

    # Readiness 声明
    full_identifiers: list[str] = Field(default_factory=list)
    # 精确标识符 — 有任意一个就 full（API 返回唯一结果）
    # 例：["order_number", "tracking_number"]

    degraded_identifiers: list[str] = Field(default_factory=list)
    # 模糊标识符 — 有任意一个就 degraded（API 可能返回多条）
    # 例：["customer_name", "customer_identifier"]

    provides_params: list[str] = Field(default_factory=list)
    # 执行后能提供的参数（用于 resolution chain）
    # 例：["customer_name", "customer_identifier", "email"]
```

readiness 逻辑：
- `full_identifiers` 和 `degraded_identifiers` 都为空 → 永远 full（RAG、catalog）
- 有 `full_identifiers` 中的任意一个 → full
- 有 `degraded_identifiers` 中的任意一个 → degraded
- 都没有 → insufficient

**砍掉的模型：** `ParamGroup`、`ObjectTypeContract`、`ToolContract`（含 `fallback_contract`）、`ParamSpec`、`degraded_min_groups`、`allow_degraded`。

### ToolReadiness — 运行时就绪度评估结果

```python
class ToolReadiness(_ToolModel):
    tool_name: str
    can_execute: bool
    quality: Literal["full", "degraded", "insufficient"] = "full"
    matched_identifier: str = ""      # 匹配到的标识符名
    missing_identifiers: list[str] = Field(default_factory=list)
    # 缺失的标识符（用于 clarification 和 resolution）
    reason: str = ""
```

### CandidatePath / PathEvaluation — 保持不变

```python
class CandidatePath(_ExecutionModel):
    tool_name: str
    readiness: ToolReadiness
    selection_score: float = 0.0
    effective_priority: float = 0.0
    role: str = "primary"

class PathEvaluation(_ExecutionModel):
    recommended_action: Literal["execute", "clarify"] = "execute"
    executable_paths: list[CandidatePath] = Field(default_factory=list)
    blocked_paths: list[CandidatePath] = Field(default_factory=list)
    clarification_context: ClarificationFromPaths | None = None

class ClarificationFromPaths(_ExecutionModel):
    missing_by_path: dict[str, list[str]] = Field(default_factory=dict)
    # key = tool_name, value = 缺失的 identifier 名列表
```

---

## 各 Tool 的声明

### QuickBooks tools（需要 identifiers）

| Tool | full_identifiers | degraded_identifiers | provides_params |
| --- | --- | --- | --- |
| customer_lookup_tool | `[customer_identifier]` | — | `[customer_name, customer_identifier, email]` |
| order_lookup_tool | `[order_number]` | `[customer_name, customer_identifier]` | `[order_number, customer_name, invoice_number]` |
| invoice_lookup_tool | `[invoice_number]` | `[order_number, customer_name]` | `[invoice_number, order_number, customer_name]` |
| shipping_lookup_tool | `[tracking_number]` | `[order_number, customer_name]` | `[tracking_number, order_number, customer_name]` |

### Catalog / RAG / Documents tools（不需要 identifiers）

| Tool | full_identifiers | degraded_identifiers | provides_params |
| --- | --- | --- | --- |
| catalog_lookup_tool | — | — | `[catalog_number, product_name, business_line]` |
| pricing_lookup_tool | — | — | — |
| technical_rag_tool | — | — | — |
| document_lookup_tool | — | — | — |

identifiers 都为空 → 永远 full → 永远可执行。

---

## 核心逻辑

### 1. check_readiness — 就绪度判断

```python
# src/tools/readiness.py

def check_readiness(
    capability: ToolCapability,
    available_params: dict[str, str],
) -> ToolReadiness:
    """10 行核心逻辑。"""
    if not capability.full_identifiers and not capability.degraded_identifiers:
        return ToolReadiness(tool_name=capability.tool_name, can_execute=True,
                             quality="full", reason="No identifiers required.")

    for p in capability.full_identifiers:
        if _has_param(p, available_params):
            return ToolReadiness(tool_name=capability.tool_name, can_execute=True,
                                 quality="full", matched_identifier=p,
                                 reason=f"Full identifier '{p}' available.")

    for p in capability.degraded_identifiers:
        if _has_param(p, available_params):
            return ToolReadiness(tool_name=capability.tool_name, can_execute=True,
                                 quality="degraded", matched_identifier=p,
                                 reason=f"Degraded identifier '{p}' available; results may not be unique.")

    all_ids = capability.full_identifiers + capability.degraded_identifiers
    return ToolReadiness(tool_name=capability.tool_name, can_execute=False,
                         quality="insufficient", missing_identifiers=all_ids,
                         reason=f"Missing all identifiers: {all_ids}")
```

### 2. evaluate_execution_paths — 路径评估

```python
# src/executor/path_evaluation.py

_QUALITY_WEIGHT = {"full": 1.0, "degraded": 0.6, "insufficient": 0.0}

def evaluate_execution_paths(selections, object_type, available_params) -> PathEvaluation:
    paths = []
    for sel in selections:
        entry = get_registry_entry(sel.tool_name)
        if entry.capability is None:
            paths.append(CandidatePath(..., quality="full"))
            continue
        readiness = check_readiness(entry.capability, available_params)
        weight = _QUALITY_WEIGHT[readiness.quality]
        paths.append(CandidatePath(
            tool_name=sel.tool_name,
            readiness=readiness,
            selection_score=sel.match_score,
            effective_priority=round(sel.match_score * weight, 4),
            role=sel.role,
        ))

    executable = sorted([p for p in paths if p.readiness.can_execute],
                        key=lambda p: -p.effective_priority)
    blocked = [p for p in paths if not p.readiness.can_execute]

    if executable:
        return PathEvaluation(recommended_action="execute",
                              executable_paths=executable, blocked_paths=blocked)

    return PathEvaluation(recommended_action="clarify",
                          executable_paths=[], blocked_paths=blocked,
                          clarification_context=_build_clarification_context(blocked))
```

### 3. find_resolution_provider — 一步补全

```python
# src/executor/path_evaluation.py

def find_resolution_provider(path_eval, available_params) -> str | None:
    """一层 resolution：找能跑且能提供缺失 identifier 的 tool。"""
    needed = set()
    for path in path_eval.blocked_paths:
        needed.update(path.readiness.missing_identifiers)
    if not needed:
        return None

    blocked_names = {p.tool_name for p in path_eval.blocked_paths}
    for entry in list_registry_entries():
        if entry.capability is None or entry.tool_name in blocked_names:
            continue
        provides = set(entry.capability.provides_params)
        if not (provides & needed):
            continue
        # Provider 必须自身 full
        provider_readiness = check_readiness(entry.capability, available_params)
        if provider_readiness.quality == "full":
            return entry.tool_name

    return None
```

### 4. available_params 的提取

不变 — `extract_available_params()` 仍从四层来源提取参数。这个函数的复杂度是合理的，因为参数来源确实多样。

---

## 删除的代码

| 文件 | 删除内容 | 原因 |
| --- | --- | --- |
| `src/tools/models.py` | `ParamSpec`, `ParamGroup`, `ObjectTypeContract`, `ToolContract` | 被 `full_identifiers` / `degraded_identifiers` 取代 |
| `src/tools/readiness.py` | 整个旧实现（~100 行） | 重写为 ~15 行 |
| `src/executor/path_evaluation.py` | `_infer_object_type`, `_infer_provider_object_type` | 不再需要（不依赖 object_type 做 readiness 判断） |
| `routing/policies/clarification.py` | `_CRITICAL_FIELDS` dict | 被 tool 声明取代 |
| `routing/policies/clarification.py` | `_filter_critical_missing()` 函数 | 被 check_readiness 取代 |
| `routing/orchestrator.py` | `_narrow_missing_information()` 函数 | 不再需要 |

---

## 为什么不用 ParamGroup + ObjectTypeContract

之前的设计使用了 `ParamGroup`（OR 语义参数组）+ `ObjectTypeContract`（按 object_type 分 contract）+ `allow_degraded` / `degraded_min_groups`。这三者叠加后会产生组合爆炸：

- Tool A 缺 x
- Tool B 可以补 x 但 degraded
- Tool C 可以补 y 但需要 x

对于 5 个工具 + 1 条实际 resolution 路径的系统来说，这是过度设计。

实际的 readiness 问题就是：**有没有一个 identifier 可以调 API？** 有 → 执行，没有 → 补全或追问。`full_identifiers` / `degraded_identifiers` 直接表达了这个语义，不需要额外的抽象层。

---

## 加新 Tool 的体验

```python
# src/tools/inventory/capability.py
INVENTORY_CAPABILITY = ToolCapability(
    tool_name="inventory_tool",
    description="查询实时库存水平",
    supported_object_types=["product"],
    supported_demands=["commercial"],
    supported_dialogue_acts=["inquiry"],
    supported_modalities=["external_api"],
    supported_request_flags=["needs_availability"],
    full_identifiers=["catalog_number"],
    degraded_identifiers=["product_name"],
    provides_params=["catalog_number", "product_name", "stock_level"],
    returns_structured_facts=True,
    requires_external_system=True,
)
```

不需要改动的文件：routing、executor、clarification policy、任何外部映射表。

自动获得的能力：
- readiness 判断：有 catalog_number → full，有 product_name → degraded，都没有 → 补全或追问
- resolution chain：其他 tool 缺 catalog_number 时，inventory_tool 自动成为 provider 候选

---

## Anti-Patterns

1. **Tools that decide what other tools to call.** 每个 tool 返回数据，不返回指令。只有 executor 根据 tool results 决定下一步行动。
2. **Tool-specific logic in the executor.** `if tool_name == "xxx": ...` → 用 ToolCapability 字段做通用决策。
3. **外部硬编码表代替 tool 声明。** `_CRITICAL_FIELDS`、`_RESOLUTION_PROVIDERS` 都是 anti-pattern — tool 的需求由 tool 自己声明。
4. **抽象程度超过问题规模。** 5 个工具不需要通用的 contract evaluation engine。简单的 identifier 列表比 ParamGroup + ObjectTypeContract 更可维护。
5. **Degraded provider 链式解锁。** Provider 必须自身 full。不允许 degraded provider 参与 resolution — 这会引入不确定性传播。

---

## 迁移步骤

### Step 1: 简化数据模型
1. `ToolCapability` 新增 `full_identifiers` / `degraded_identifiers`
2. `ToolReadiness` 简化为 `matched_identifier` + `missing_identifiers`
3. 删除 `ParamSpec`, `ParamGroup`, `ObjectTypeContract`, `ToolContract`

### Step 2: 重写 readiness 评估
1. `src/tools/readiness.py` → ~15 行 `check_readiness()`
2. 删除 `_resolve_object_contract`、group 遍历逻辑

### Step 3: 简化 path evaluation
1. `evaluate_execution_paths` 不再需要 `_infer_object_type`
2. `find_resolution_provider` 约束：provider 必须 full
3. `_build_clarification_context` 简化为收集 `missing_identifiers`

### Step 4: 更新 tool 声明
1. QuickBooks 4 个 tool → `full_identifiers` + `degraded_identifiers`
2. Catalog / RAG / Documents → 两个列表都为空

### Step 5: 更新测试
1. `test_tool_readiness.py` — 重写为 full / degraded / insufficient 基于 identifier 的测试
2. `test_path_evaluation.py` — 简化路径评估测试
3. `test_resolution_chain.py` — 更新 resolution chain 测试

### Step 6: 清理旧代码
1. 删除 routing 中的 `_CRITICAL_FIELDS` 等遗留代码
2. 删除 `ToolCapability.required_params`（已废弃）
