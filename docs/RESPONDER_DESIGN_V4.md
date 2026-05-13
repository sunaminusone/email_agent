# Responder Design (v4)

## 定位

这是 v4 CSR 邮件副驾 **responder 层** 的设计文档。Responder 是 pipeline 的最后一环——执行器跑完后,它把工具结果合成一份 CSR 可读、可编辑的草稿。

v4 之前 responder 长在 `AGENT_ARCHITECTURE_V4.md` section 6 里只占 30 行,但实际代码体量已经超过 800 行(extractors / dedupe / sections / draft_llm / composer 几个模块加起来)。这份独立 doc 把契约和职责讲清楚,后续加工具/加业务线就不会再把 schema 知识塞进 drafting prompt。

v4 invariant: `_render_response`(`src/responser/service.py`)永远调 `render_csr_draft_response`(`src/responser/csr/composer.py`)。dormant 的七个 legacy renderer 在 `src/responser/renderers/` 里保留但不 dispatch,清理待办。

---

## Purpose

合成一份 CSR(客服代表)可审阅可编辑的邮件草稿,包含:

1. **📝 Draft reply** — LLM 起草的对客户回复正文
2. **🧭 Grounding signal** — 数据置信度 / 检索质量徽章
3. **💰 Live catalog facts / 💰 Pricing** — 来自 PG 的结构化产品/价格记录
4. **📚 Similar past inquiries** — 历史销售邮件 top-k
5. **📄 Relevant documents** — KB 文档 chunk top-k
6. **📁 Matched document files** — 工具匹配到的产品 flyer / 服务 brochure(带 presigned URL 的可点 chip)
7. **📦 Operational records** — QuickBooks 订单/发票/物流/客户
8. **⚠️ AI routing notes** — 路由层旗到的 ambiguity / handoff 警示

只有有数据的 section 才会出现 — 不灌占位符。

## Non-Goals

Responder **不**:

1. **不选工具、不执行检索、不发明事实**。只读 `ExecutionResult` 里已经放好的东西。
2. **不应该懂 tool 的字段 schema**。"`wb_dilution` 是哪个 application 的稀释比例" 这种知识属于 catalog 工具,不属于 drafter。Responder 把 `ToolResult.llm_records` 当成已经 LLM-ready 的形态消费。
3. **不**做 cross-turn memory 决策。它只读当前 turn 的执行结果。memory 更新由 ResponsePlan.memory_update 上行,但那是 contract,不是 responder 自己的决策权。
4. **不**负责为 tool 返回的 matched document files 生成 presigned URL。`document_lookup_tool` 返回的 `document_url` 已经是可 render 的链接。例外是 primary service document 这条辅助路径:当前由 responder 的 `resolve_primary_service_document()` 调 `get_primary_service_document_link()` 现取现用,它不属于 tool output contract。这条路径本质是 "resolved service → primary brochure" 的 deterministic attachment lookup,不像普通 retrieval。标为 responder 的 **known boundary leak,当前接受,不纳入本次 llm_records / prompt 去 schema 化改造范围**。

---

## Pipeline 概览

```
ExecutionResult (executor 产出)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  composer._gather_inputs                             │
│   ├── collect_calls_by_bucket                        │
│   │    └── dedupe_calls (按 tool_name 去重)          │
│   ├── extract_historical_threads                     │
│   ├── extract_technical_doc_matches                  │
│   ├── extract_document_files                         │
│   ├── extract_structured_records                     │
│   ├── extract_operational_records                    │
│   ├── resolve_primary_service_document               │
│   ├── collect_routing_notes                          │
│   └── build_trust_signal                             │
└──────────────────────────────────────────────────────┘
    │
    ├──> _build_panel_section_pairs
    │      (sections.py 把每类数据 format 成 Slack 风格文本 + ContentBlock)
    │
    └──> generate_draft / stream_draft
           (draft_llm.py 用 LLM 把 records 合成对客户的 prose)
    │
    ▼
_assemble_composed_response
    │
    ▼
ComposedResponse (message + content_blocks + debug_info)
```

`composer.py` 是 thin orchestrator,没有业务逻辑;各 step 各司其职。

---

## ⭐ 新契约 — `ToolResult.llm_records`

### 为什么要新契约

当前 `draft_llm._DRAFT_SYSTEM_PROMPT` 200 行里 ~150 行是在教 LLM "字段是啥意思":

```
- "Western blot" / "WB"               → `wb_dilution`
- email_status: NotSet 意思是 NEVER sent,not "we have no record"
- service-flyer 的 `phase_name` 不是 plan total,phase price 不能加总
...
```

这些是 **tool schema 知识**,不该住在 drafting prompt 里。新加工具/字段就要去改 drafter prompt,职责完全错位。

### 契约

`ToolResult` 增加一个并行字段:

```python
class ToolResult(_ToolModel):
    tool_name: str
    status: str = "empty"
    primary_records: list[dict[str, Any]]   # 原样,raw — 给 debug/前端/API 消费
    llm_records:    list[dict[str, Any]]    # ★ 新增 — 给 drafter LLM 消费
    supporting_records: list[dict[str, Any]]
    structured_facts: dict[str, Any]
    unstructured_snippets: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    errors: list[str]
    debug_info: dict[str, Any]
```

- `primary_records` **不变**,raw schema 原样保留(debug/前端/dedup identity key 等)
- `llm_records` 是同样的 records,但每条经过 tool 侧的 `serialize_for_llm` 转换:
  - 字段名语义化(`wb_dilution` 保留 ✓ / `email_status` → 拆成 `email_sent` 布尔 + `email_status_detail`)
  - 字段值的 sentinel 还原(`sequence: "full"` → `(not on file)` / `email_status: NotSet` → `email_sent: false`)
  - 不相关的字段省略(antibody record 不应该有 `lnp_type` 字段;现在 LEFT JOIN 后所有 None 都被 render 忽略,但 raw record 里仍存在)
- `llm_records` 与 `primary_records` 是 **1:1 对位** 的并行列表:同一 index 表示同一条底层 record 的 raw 版和 LLM 版
- responder 入口的 `dedupe_calls` 如果折叠了同名 tool,必须按同一个 identity 函数 **同步 merge `primary_records` 和 `llm_records`**;不能只 union raw 否则 LLM-ready view 会在 dedup 视图里丢失
- **`dedupe_calls` 的 identity function 永远作用在 `primary_records` 上**;`llm_records` 只是同一底层 record 的 LLM view,按对位关系随 merged raw record 一起移动,不单独计算 identity。这是为了保证 `llm_records` 可以自由改名、拆字段、归一化,不会反向污染 dedup contract
- 当 tool 没实现 `serialize_for_llm` 时,fallback 用 `primary_records` 原样(向后兼容)

#### 镜像边界

本轮仅 `primary_records` 引入并行 `llm_records`;`supporting_records` 与 `unstructured_snippets` 继续要求 tool 直接产出通用、可读、近似 LLM-ready 的形态,不再额外镜像。理由:

- `supporting_records` 目前不是 responder drafter 的主输入面
- `unstructured_snippets`(RAG chunk)的 shape 已经稳定且通用(`source_type / title / content / source_path`)
- 把镜像机制扩到所有 record-like 字段会让 doc 和实现复杂度翻倍而收益边际

### 命名规范

字段名走"中等清晰"原则 —— 缩写要约定俗成,不要圈外人看不懂:

| 可保留 | 要展开 |
|---|---|
| `wb_dilution` (WB 行业惯用) | `txn_date` → `transaction_date` |
| `lnp_type` (LNP 行业惯用) | `last_updated_at` → 保留就行 |
| `catalog_no` | `email_status: NotSet` → `email_sent: false` |
| `elisa_dilution` | `print_status: NotSet` → 同上 |
| `ihc_dilution` / `icc_dilution` / `fcm_dilution` | `txn_date` → 文档语义 "(invoice creation date)" |
| `target_antigen` | sequence sentinels `"full" / "" / "N"` → `"(not on file)"` |

更长的命名(`recommended_dilution_western_blot`)反而冗长,LLM 也不会因为字段长就更准 —— 字段 doc + tool 侧合理 sentinel 处理是更重要的工具。

### 谁负责 serialize

**Tool 侧**。每个工具 wrapper 实现自己 records 的 `serialize_for_llm`:

```python
# src/tools/catalog/product_tool.py
def execute_catalog_lookup(request) -> ToolResult:
    raw_matches = lookup_catalog_products(...).get("matches", [])
    return ok_result(
        tool_name="catalog_lookup_tool",
        primary_records=raw_matches,
        llm_records=[serialize_match_for_llm(m) for m in raw_matches],
        ...
    )
```

`serialize_match_for_llm` 可以住 `src/catalog/retrieval/llm_serializer.py` 或同名旁边文件,反正它知道 catalog 三业务线 schema。其他 tool 同理(`src/quickbooks/llm_serializer.py` 等)。

### Drafter 怎么消费

`draft_llm.py` **不**直接碰 `ToolResult`。真正的接入点在 `extractors.py`:

- `extract_structured_records` / `extract_operational_records` 优先读 `call.result.llm_records`
- 若 `llm_records` 为空,再 fallback 到 `primary_records`
- `render_record_for_llm` 只负责把已经 llm-ready 的 dict dump 成 `key: value`,不再承担 schema 解释

也就是说,迁移后 drafter 看到的输入已经是 llm-ready record,而不是再从 raw record 临场猜字段语义:

```python
def extract_structured_records(calls):
    for call in calls:
        records = call.result.llm_records or call.result.primary_records
        ...
```

不再做任何字段语义注释 — 那是 tool 的责任。

---

## Drafting fragments

字段语义砍掉之后,prompt 里还会留三类**真正属于 drafting 策略**的规则:

1. **核心策略**(应答 asked_focus、不越界、不发明、stay in same language)→ `_DRAFT_SYSTEM_PROMPT_CORE`,常驻
2. **Grounding fallback** → `_UNGROUNDED_RULE` / `_WEAKLY_GROUNDED_RULE`,按 trust_signal 条件加
3. **Tool-specific drafting nuance** → 不可避免要留一点(比如"service-flyer 价格别加总"、"narrow factual ask 不出 flyer chip"),抽到 `src/responser/csr/prompts/<topic>.md` 按 tool 条件加载

### Fragment 加载机制

```python
# src/responser/csr/prompts/__init__.py
_FRAGMENTS: dict[str, str] = {
    "pricing_lookup_tool": _load("pricing_semantics.md"),
    "document_lookup_tool": _load("document_link_rendering.md"),
    # ...
}

def fragments_for_tools(fired_tool_names: set[str]) -> list[str]:
    return [_FRAGMENTS[t] for t in sorted(fired_tool_names) if t in _FRAGMENTS]
```

`_build_system_prompt` 拼接:

```python
def _build_system_prompt(*, grounding_status, primary_service_document, tools_fired):
    parts = [_DRAFT_SYSTEM_PROMPT_CORE]
    parts.extend(fragments_for_tools(tools_fired))
    if grounding_status == "ungrounded":
        parts.append(_UNGROUNDED_RULE)
    elif grounding_status == "weakly_grounded":
        parts.append(_WEAKLY_GROUNDED_RULE)
    if primary_service_document:
        parts.append(_PRIMARY_DOCUMENT_RULE)
    return "\n\n".join(parts)
```

按 turn fire 了哪些 tool 条件性加载 → 单 turn prompt token 数下降;新 fragment 加一个 markdown 文件就行,不动 draft_llm.py。

---

## 模块职责

```
src/responser/
├── service.py              — entry,永远走 csr_draft path
├── composer.py             — orchestrator:_gather_inputs + 拼装 ComposedResponse
└── csr/
    ├── extractors.py       — 把 ExecutedToolCall 列表按 tool 分桶 + 提取 records
    ├── dedup_keys.py       — ★ tool 级 identity 函数,collect_calls_by_bucket 入口处一次性去重
    ├── sections.py         — 各类 panel 的 Slack 风格文本格式化
    ├── prompts/            — ★ tool-specific drafting fragments(待建)
    │   ├── pricing_semantics.md
    │   ├── document_link_rendering.md
    │   └── ...
    └── draft_llm.py        — LLM 起草 + system prompt 组装
```

### `extractors.py`

把 `ExecutionResult.executed_calls`(raw 列表,可能有 cross-group 重复)分桶到 5 类:`historical / technical_docs / document_files / structured / operational / unknown`。

入口处先调 `dedupe_calls`(见下) — 所有 extractor 看到的都是去重过的 view。迁移后 structured / operational extractor 负责优先消费 `llm_records`,缺省时 fallback 到 `primary_records`。各 extract_* 函数不再做 dedup,只做取数 + `_source_tool` 标注。

### `dedup_keys.py`

`executed_calls` 是 raw audit list — 每个 dispatch 一条,包括 cross-group cache reuse 和 retry-with-fallback 产生的同名 tool 多次记录。`dedupe_calls` 按 tool_name 折叠成单 entry,并按同一个 identity 函数同步 union `primary_records` / `llm_records`,保证 responder 看到的 raw view 和 llm-ready view 仍然一一对应。

加新 tool: 在 `_DEDUP_KEY` 加一行,声明这 tool 的 record identity 字段。没加 → 不去重 + warn(safe default,不会丢数据)。

### `sections.py`

每个 panel 一个 `format_*_section` 函数,产出 Slack 风格 markdown 文本(用 `*bold*`、缩进、emoji header)。

注意:Slack inline formatter([app.js:124](../frontend/app.js#L124))不解析 markdown link,所以 panel 里**不要**塞 `[Title](url)` —— URL chip 走单独路径(chat-document-actions, app.js:590)由前端独立渲染。

### `prompts/` 目录(待建)

存放 tool-specific drafting fragment 的 markdown 文件。命名按 tool_name 或 topic(优先 topic — 一个 fragment 可能跨 tool)。

### `draft_llm.py`

- `_DRAFT_SYSTEM_PROMPT_CORE` — schema-agnostic 的核心规则,~50 行
- `_build_system_prompt(...)` — 条件拼接 fragment
- `_build_draft_prompts(...)` — 把 extractor 产出的 llm-ready records 渲染进 user prompt
- `generate_draft / stream_draft` — LLM 调用
- `render_record_for_llm` — 把 llm-ready dict dump 成 `key: value` 行,不做字段注释

---

## Migration Phases

从现状(prompt 200 行 with 150 行 schema 知识)走到目标(prompt ~80 行 + tool 侧 llm_records)的步骤。**每阶段前 capture 10-20 个代表 query 的 LLM draft 输出做 golden**,阶段后对比,确保行为等价或更好。

| Phase | 范围 | 砍 prompt 行号 | 加 tool serializer |
|---|---|---|---|
| **0** | 写 doc + 拍契约(本文档) + golden capture infra | — | — |
| **1** | catalog 三业务线(antibody/cart/lnp) | lines 88-134 | `src/catalog/retrieval/llm_serializer.py` |
| **2** | QuickBooks 套件 | lines 135-157 | `src/quickbooks/llm_serializer.py` |
| **3** | pricing tool + service-flyer fragment | lines 60-87 | `src/tools/catalog/pricing_serializer.py` + `prompts/pricing_semantics.md` |
| **4** | "record found 字段缺" 3 分支收敛 | lines 42-68 | 用 sentinel + fragment 替代 |
| **5** | 总清,draft_llm 砍到 ~80 行 | — | — |

### Phase 0 详细 — golden capture 两层验证

每个 migration phase 都需要 **前后对比 LLM draft 行为**,所以先把 capture infra 建好。两层互补:

1. **单测层** — 在 `tests/test_response_service.py` 附近补 2-4 个 focused tests(借现成 `_PromptCapturingLLM` pattern):
   - `llm_records` 优先于 `primary_records` 被消费
   - 缺 `llm_records` 时 fallback 到 `primary_records` 不报错
   - `dedupe_calls` 折叠同名 tool 后 `llm_records` 与 `primary_records` 仍 1:1 对位
   这层负责 contract 不回退,跑得快,每次 phase 推进必跑。
2. **Snapshot 层** — 新建 `tests/snapshot_csr_draft_baseline.py`(沿用现有 `tests/snapshot_rag_baseline.py` 风格):
   - 输入: 10-20 个代表 query(覆盖 CAR-T / LNP / antibody / QB / pricing / service-flyer / 多 SKU)
   - 输出: 每 query 的 LLM draft + panel sections JSON
   - 每 phase 前手跑一次存 baseline,phase 后再跑做 diff
   这层捕真实 LLM 行为,**预期某些 phase 是零差异**(纯重构),某些 phase 是**等价或改善**(prompt 砍了之后 LLM 应该不会更差)。

跑前后两次,人眼看 diff 决定 phase 是否落地。不进 CI(LLM 调用费时费 token)。

### Phase 1 详细

理论上 step 1-3 是 **零行为变化的纯铺路**(`llm_records` 全空,fallback 走 `primary_records`,golden 应不变),回归风险最低:

1. **ToolResult schema 加 `llm_records: list[dict] = []`**
   ([src/tools/models.py](../src/tools/models.py)) — 默认空,所有现有 tool 透明兼容
2. **`dedup_keys.py` 同步 merge `llm_records`**
   identity 仍跑在 `primary_records` 上,按 index 对位携带 `llm_records[i]`
3. **`extractors.py` 优先读 `llm_records`,缺省 fallback `primary_records`**
   `extract_structured_records` / `extract_operational_records` 加 `records = call.result.llm_records or call.result.primary_records`
4. **新建 `src/catalog/retrieval/llm_serializer.py`**
   - `serialize_antibody_record(raw) -> dict`(展开 immunogen / sequence sentinel、去 None 字段)
   - `serialize_cart_record(raw) -> dict`
   - `serialize_lnp_record(raw) -> dict`
   - 入口 `serialize_catalog_record(raw)` 按 `business_line` dispatch
5. **`src/tools/catalog/product_tool.py` emit `llm_records`**
   `primary_records=raw_matches, llm_records=[serialize_catalog_record(m) for m in raw_matches]`
6. **第一波 golden capture** — 预期对 catalog query 零差异(字段映射等价)
7. **砍 `_DRAFT_SYSTEM_PROMPT` lines 88-134** (CAR-T / antibody / LNP 字段语义)
8. **第二波 golden capture** — 预期等价或改善(LLM 不再被冗长字段 map 误导)

后续 phases(QB / pricing / record-found-but-missing)同模式: schema → dedup → extractor → emit → golden(零差异)→ 砍 prompt → golden(等价或改善)。

---

## Open Questions

- **`MergedResults.primary_facts` 是不是也要对应 `llm_facts`?**`merged_results` 是 tool_name → structured_facts dict,目前 drafter 不读它,前端读。暂不改。
- **`extract_structured_records.pricing_records` 特殊路径**(从 structured_facts 拉而不是 primary_records) 跟 llm_records 怎么协调?Phase 3 处理。
- **legacy renderer 清理**仍在 backlog,跟本次 refactor 解耦,可分开做。

---

## 跟其他 v4 doc 的关系

- **AGENT_ARCHITECTURE_V4.md section 6**:精简到 "see RESPONDER_DESIGN_V4.md",保留 v4 invariant("永远 csr_draft") 一行
- **TOOL_CONTRACT_DESIGN_V4.md**:加一节描述 `serialize_for_llm` 是 tool wrapper 的 SHOULD(不是 MUST,旧 tool 不实现也能 fallback);命名规范 link 过来
- **EXECUTOR_DESIGN_V4.md**:不动 — executor 跟 `llm_records` 完全无关
