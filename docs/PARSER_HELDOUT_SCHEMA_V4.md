# parser_heldout_benchmark schema (v4)

> **v4 note**: parser held-out benchmark schema 在 v4 沿用 —— parser 的 intent / flag / entity 提取在 v4 仍然是 retrieval scoping 和 draft 生成的关键输入。"routing 字段决定下游路径"在 v4 解读为"这些字段决定 retrieval scope + draft prompt 输入",不是"决定 customer-facing 的 clarify/handoff 阻塞"。Schema 本身和评估指标都没变。

held-out benchmark 的职责分两层:
- **主职责**:稳态评 parser 是否把消息送上对的下游路径(retrieval scope + draft scope)
- **副轴**:保留 retrieval bucket 监督信号(为后续评 RAG bucket 选择质量留 ground truth)

> "这条用户消息被 parser 解析后,routing 字段是否足以把系统送上对的下游路径?retrieval 字段是否准确指向应该查的知识桶?"

不是 taxonomy 讨论场(那是 `parser_coverage_suite.json`),不是系统效果终审庭(留给真 e2e set,目前不存在)。

## Two-tier architecture

| 层 | 字段 | invariant | 评估目标 |
|---|---|---|---|
| 语义摘要层 (retrieval-relevant) | `primary_intent` | 这条 query 要从哪个 RAG bucket 取知识才能被回答 | RAG bucket 选择是否对 |
| 执行控制层 (routing-relevant) | `route_splitter_flags` + `dialogue_act` + `needs_human_review` | 用户实际要哪些动作 / 触发哪些 routing fork | 路径分叉决策是否对 |

**两层 orthogonal** — 一层错不影响另一层;同一条 query 可以"primary 错但 routing 对"或反之。Metric 必须独立计算,不合并 score。

**关键反直觉**:`primary_intent` **不**回答"系统该执行什么动作 / 走哪条能力路径" —— 那是 routing 层的事。`primary_intent` 只回答"哪个知识桶里的 chunk 能直接回答这条 query"。两者在大多数情况下是不同问题:同一条 query 可能 routing 路径只走 commercial 报价,但 retrieval 仍要从 workflow bucket 取流程描述作为答复支撑。

## Schema (A-Prime / F-Tiered)

```json
{
  "id": "heldout_<primary_intent>_<slug>",
  "query": "<full inbox text>",
  "source": "real_inbox",

  "primary_intent": "<one of 16 canonical enum>",
  "dialogue_act": "inquiry" | "selection" | "closing",
  "needs_human_review": false,

  "route_splitter_flags": [
    "needs_price" | "needs_quote" | "needs_timeline" |
    "needs_protocol" | "needs_documentation" |
    "needs_shipping_info" | "needs_customization"
  ],

  "auxiliary_flags": [
    "needs_troubleshooting" | "needs_recommendation" | "needs_regulatory_info" |
    "needs_availability" | "needs_comparison" | "needs_sample" |
    "needs_order_status" | "needs_invoice" | "needs_refund_or_cancellation"
  ],

  "rationale": "<标注理由>"
}
```

## Field semantics

### `primary_intent` (string, required)
16 canonical enum,one of:
- product_inquiry / technical_question / workflow_question / model_support_question
- service_plan_question / pricing_question / timeline_question / customization_request
- documentation_request / shipping_question / troubleshooting / order_support
- complaint / follow_up / general_info / unknown

**primary_intent 的下游实际用途**(锚点 —— 这是它**唯一**会被消费的地方):
1. **给 RAG 选 bucket** —— `_SEMANTIC_INTENT_BUCKET_MAP` 1:1 投影到 RAG bucket
2. **帮 query rewrite** —— rewrite 模板按 intent 选风格 / 关键词
3. **帮 retrieval 聚焦** —— `_SECTION_TYPE_BOOSTS` 按 bucket 加权 section_type

它**不**驱动 routing 主分叉(那是 flags + dialogue_act 的事)。

**RAG-relevant vs non-RAG intents 的监督语义**:
- 对 `technical_question` / `workflow_question` / `service_plan_question` / `pricing_question` / `timeline_question` / `customization_request` / `documentation_request` / `model_support_question` / `product_inquiry` / `troubleshooting` 等 **RAG-relevant** intents,primary_intent 监督**知识桶选择**(走 RAG retrieval)
- 对 `shipping_question` / `order_support` / `complaint` / `general_info` / `follow_up` / `unknown` 等 **non-RAG** intents,primary_intent 仍然表示**主语义处理类型**,只是它映射到的是 **non-RAG handler**(operational system / placeholder / handoff 等),而不是 RAG bucket

**invariant**: **dominant retrieval ASK** —— "客服回答这条 query 时,需要引用**最多核心 chunk** 的是哪个 bucket?那个 bucket 就是 primary_intent。"

#### 三条决策规则(可操作化拆解)

**规则 1 —— primary_intent 优先只看 knowledge ASK**

用户**明确要拿到什么知识内容**?客服回答时**真正需要引用哪类 chunk** 才能支撑回答?那个 chunk 所在 bucket 就是 primary_intent。

**规则 2 —— 纯 disposition / intent 表达不算 knowledge ASK**

下面这类语句本身**不**是 knowledge ASK,只影响 routing flags(`needs_customization` / `needs_quote` / `needs_human_review` 等),不直接决定 primary_intent:
- "we are interested in X"
- "we are looking for X"
- "please contact us to discuss"
- "we would like to know more / explore"
- "we are exploring partnership..."

它们是**商业意向 / 项目姿态 / demand 信号**,在 routing 层高价值,但在 retrieval 层不构成"知识 ASK"。

**规则 3 —— Capability inquiry 归 Fallback**

形如 "do you develop X / do you offer X / do you support X / can you make X / which X do you offer / what X are available / what types of X / what formats do you support" 的 capability inquiry(**yes/no 或 enumeration 形式均可**),**不视为具体 knowledge ASK**。

这类 query 的 primary_intent 一律按 Fallback 处理:根据**客服回复时最需要引用的 capability / scope / introduction chunk 所属 bucket** 选择。

例:custom service → `customization_request`;catalog item → `product_inquiry`;shipping / order / complaint → 对应 operational bucket。

**Fallback —— 整条 query 全是 intent 表达,无 knowledge ASK 时**

不能留空,也不能强行填 `unknown`(因为客服仍要从某个桶拉介绍/scope chunk 回复)。规则:

> primary_intent = "客服回复时最需要引用的 **scope / introduction / capability** chunk 所在 bucket"

具体细则:
- 意向指向 **custom service / custom build / 客户特定 spec** → `customization_request`
- 意向指向 **catalog item / 产品咨询** → `product_inquiry`
- 意向指向 **shipping / order / complaint** → 对应 `shipping_question` / `order_support` / `complaint`
- 其他纯姿态(eg. "looking for partnership / exploring vendors") → `general_info` 或 `unknown`(看上下文)

**简单优先级**:有 knowledge ASK → 规则 1;无 knowledge ASK → Fallback。规则 2(disposition 表达)和 规则 3(capability inquiry)都用来排除**伪装成 ASK 的非 knowledge ASK**。

#### 禁用的判定语(routing 视角,污染 retrieval 评估)
- ❌ "系统该走哪条能力路径 / 该 perform 什么动作"
- ❌ "用户要系统先解决哪个问题"
- ❌ "对应哪条 handler / pipeline"

**应该用的判定语**(retrieval 视角):
- ✅ "在语义上最该往哪个知识桶里找核心内容"
- ✅ "哪个 bucket 的 chunk 直接是 query 的答案"
- ✅ "如果只能 retrieve 一个 bucket,选哪个能命中最多有用 chunk"

**为什么这条要严格**:`technical_question` / `workflow_question` / `service_plan_question` / `customization_request` 在 routing 视角下边界糊(都可能触发同一组 flags),但在 retrieval 视角下是 4 个不同的 RAG bucket,各自命中不同 section_type。一旦标注用 routing 思维选 primary_intent,bucket 监督信号就毁了。

#### Worked example —— retrieval vs routing 的差别

> "Could you provide the workflow for this CAR-T service and an estimate of the fees?"

**routing 思维**(❌ 不要这么标 primary_intent):
- "系统先 fulfill 哪个动作? 报价 vs 流程?"
- 容易卡住,或随便选一个

**retrieval 思维**(✅ 正确):
- 这条 query 的**核心内容请求**是什么? —— "CAR-T service 的 workflow"(主体长描述)
- "estimate of fees" 在多数 ProMab 对话里是 templated/short 回答,不需要从 RAG bucket 拉大段 chunk
- 真正要从知识桶取的核心是 workflow / service_plan 的流程描述
- ⇒ `primary_intent = "workflow_question"`(或 `service_plan_question`,取决于 CAR-T 知识在 KB 里实际归到哪个 bucket)

**routing 层独立标**(跟 primary_intent 不对齐):
- `route_splitter_flags = {needs_protocol, needs_price}`(两个动作都触发)
- `dialogue_act = "inquiry"`
- `needs_human_review = false`

**结果**:`route_splitter_flags` 反映 query 的**多动作请求**,`primary_intent` 反映 query 的**核心知识请求** —— 两个独立维度,各自服务下游不同消费点。

#### Worked example —— knowledge ASK vs intent 表达

> **Query A**: "We are interested in your custom LNP service."

- 全句 intent 表达,**无** knowledge ASK
- 走 **Fallback**:意向指向 custom service → `primary_intent = customization_request`(客服回复要引用 custom LNP 桶的 scope / capability 介绍 chunk)
- routing flags: `{needs_customization}`

> **Query B**: "We are interested in your custom LNP service and would also like a recommended protocol."

- 含明确 knowledge ASK("recommended protocol")+ intent 表达
- 走 **规则 1**:knowledge ASK 决定 primary —— 客服引用最多 chunk 的桶是 protocol/workflow → `primary_intent = workflow_question`(或 technical_question,看 KB 里 protocol 实际归到哪个 bucket)
- routing flags: `{needs_customization, needs_protocol}`

**关键观察**:Query A → B 仅加一句 knowledge ASK,primary_intent 从 `customization_request` **翻转**到 `workflow_question`。intent 表达本身不锁定 primary_intent;一旦出现 knowledge ASK,primary 就转给后者。`needs_customization` flag 仍在 routing 层保留,两层 orthogonal。

### `dialogue_act` (string, required)
3 enum:
- `"inquiry"` — 用户在问问题 / 提请求
- `"selection"` — 用户在**回应 prior clarification**,且消息语义上表达了对某个候选项的**选择或缩小**(eg. "yes the second one" / "let's go with option B" / "I want the 1mg one")
- `"closing"` — 客气话 / 确认 / 无 actionable("Thanks!" / "Solid plan!" / "We'll start on this today")

**注意**:`selection` 的判定**只看用户消息 + prior clarification 上下文**,跟 parser 内部 confidence / index mapping 无关 —— 后者属于模型输出评估,不进 schema 定义。换言之:gold label 不应依赖任何当前 parser 实现细节。

**determines**: routing fork "execute vs respond"(closing → 走 respond 不 execute)

#### Precedent —— selection vs closing 边界(2026-04-26 拍板)

**判定优先级**:
- 只要邮件里出现**明确选项落点**(ordinal "second option" / 命名方法 "lentiviral method" / catalog identifier "CAT# 20008" / 规格 "1 mg size" / 配置 "monoclonal option"),就标 `selection` —— 即使后跟 "Thank you" / "Best regards" 礼貌结尾。
- `closing` 只用于**没有实质选择动作**的纯确认/致谢("Sounds good. Thank you for the update.")。
- forward action ("Please proceed" / "Please let us know next steps") 不影响 selection 判定 —— 已选定 + 推进是 selection 范畴。

**翻转示例**:
- "We will start with this option. Best regards" → `closing`(单数指代不明示选哪个,纯启动承诺)
- "We will take the lentiviral method. Thank you very much." → `selection`(named option pick,礼貌结尾不降级)
- "Sounds good. Thank you for the update." → `closing`(无 actionable,纯 acknowledgement)
- "Let's move forward with CAT# 20008." → `selection`(catalog identifier 是显式选项落点)

### `needs_human_review` (bool, required)
safety / escalation 信号,**单独成字段** —— policy 信号 ≠ user-demand,不应跟 demand flags 放一起。
- `true` 当 query 含敏感内容 / 风险信号 / parser 拿不准要人工 escalation
- 触发 routing 直接 handoff(跳过 execute)

#### Precedent —— Regulatory submission inquiry 自动触发

涉及监管申报 / 合规审批的 inquiry,即使用户没用 escalation 措辞,**`needs_human_review = true`**:
- IND / NDA / BLA / CTA filing
- Phase I / II / III clinical trial(GMP-scale 制造或文档)
- GMP / GLP / GxP 合规 deliverables
- regulatory CMC documentation(申报用)
- 涉 FDA / EMA / NMPA 等监管机构 directive

**理由**:此类 inquiry 客服 stand-alone 不能直接处理,必须 escalate 合规 / PM / regulatory affairs review。漏打会让 routing 跳过合规审查直接 execute,产生重大业务风险。

**Worked example**:"Request a quote for CAR-T manufacturing for Phase I clinical trial + IND CMC docs" → `needs_human_review = true`(IND filing + Phase I 双重监管信号),即使用户语气专业平和。

> _Reviewer note_: 这条 precedent 把 needs_human_review 从"用户措辞触发"扩到"业务上下文触发",依赖标注人 ProMab 业务知识(类似 needs_customization precedent)。parser baseline 大面积漏属于预期信号。

#### Precedent —— Operations / legal / engagement-model questions 自动触发

涉及**客户方与 ProMab 间合作结构 / 合同关系 / 设施准入 / 现场操作权限**的 structural inquiry,即使无 safety / regulatory 信号,**`needs_human_review = true`**:

- 客户方人员能否在 ProMab 设施内做实验 / 现场操作 / on-site supervision
- 客户方能否监督 ProMab 员工(反向监督关系)
- subcontractor / middle-person / consultant 中介 arrangement / contractual structure
- shared workspace / 实验室共享 / facility access 请求
- 责任边界 / liability allocation / IP ownership 中介结构

**理由**:此类 inquiry 涉及**合同关系 / 责任边界 / 设施准入 / 现场操作权限 / 合规与保险风险**,客服 stand-alone 不能直接 commit(任何承诺都触发 contractual / insurance / liability 责任);必须 escalate operations / legal / BD review。漏打会让 routing 直接 execute,产生重大 contractual 风险。

**与 backlog #9 `needs_human_contact` 区分**:本 precedent 触发 `needs_human_review` 是**系统判断**(structural/legal complexity 需 PM 介入);backlog #9 的 `needs_human_contact` 是**用户主动要 live conversation**(约 call / Zoom / "let's discuss")。两者正交,可同时 true。

**Worked example**:"is it possible for me... to supervise a member of your team or perform the experiments myself in your facilities. ... do I need to be a subcontractor with you as middle-person?" → `needs_human_review = true`(facility access + on-site operation + subcontractor structure 三重 operations/legal 信号),即使整体语气专业平和、无 safety/regulatory 词。

> _Reviewer note_: 这条 precedent 把 needs_human_review 从 safety / regulatory submission 扩到 operations / legal / engagement model 维度,依赖标注人 ProMab 业务知识(类似 regulatory submission precedent + needs_customization precedent)。parser baseline 大面积漏属于预期信号 —— parser 缺业务先验,无法稳定识别 facility/legal/contractual 信号触发 escalation。

#### Precedent —— Customer complaint relay 自动触发

涉及客户**对 ProMab 产品/服务表达不满 / 报告产品性能问题 / 第三方 relay complaint** 的 inquiry,即使 substantive ASK 是技术诊断,**`needs_human_review = true`**:

- 显式 "complaint" / "dissatisfied" / "not working as expected" / "didn't work" 措辞
- 第三方 distributor / agent / reseller relay 客户问题
- 产品故障报告(too many bands / no signal / non-specific binding / contamination / cells died / batch failure 等)
- 售后纠纷(quality dispute / batch consistency 投诉)

**理由**:complaint 涉 customer-relationship risk + brand reputation + 潜在 QA 调查 / lot 追溯 / refund/replacement 决策,客服 stand-alone 不能直接 close,必须 escalate QA / customer-success / AE review。即使 substantive ASK 看似纯技术,handle 不当会激化客户不满或漏掉系统性产品问题信号。

**与 backlog #9 `needs_human_contact` 区分**:本 precedent 是**系统判断**(complaint risk 需 careful handling),不是用户主动要 live conversation。两者正交,可同时 true。

**与 Q22 commercial commitment gray zone 区分**:commercial commitment(discount approval 等)是商业决策但客户**未表达不满**,当前不入 precedent;complaint 是客户**已表达不满**,触发新 precedent。两个 gray zone 正交分类。

**Worked example**:"We have a customer complaint about cat# 30696. They used it in WB and got a lot more bands than expected. ... Do you have suggestions to improve the results or an explanation?" → `needs_human_review = true`(complaint relay + 第三方中介 + 产品故障报告三重信号),即使 substantive ASK 是 routine WB troubleshooting,primary_intent 仍标 troubleshooting(retrieval 维度)而非 complaint(complaint framing 由 needs_human_review 在 routing 层捕获)。

> _Reviewer note_: 这条 precedent 把 needs_human_review 扩到 customer-relationship 维度。primary_intent 与 needs_human_review 解耦 —— complaint relay 不强制 primary_intent=complaint,允许 troubleshooting / order_support / shipping_question 等 RAG-relevant intent 配 needs_human_review=true,反映"技术诊断 + 客户关系 escalation"的正交两层。

### `route_splitter_flags` (set of str, required)
7 个 **high-frequency** user-demand splitter,multi-label set。覆盖主流 inbox 80%+ routing 分叉:

| flag | 触发 | demand 类 |
|---|---|---|
| `needs_price` | "how much / cost / 多少钱" | commercial |
| `needs_quote` | "send me a quote / 报价" | commercial |
| `needs_timeline` | "how long / lead time / when / 什么时候" | commercial |
| `needs_protocol` | "protocol / procedure / SOP / 流程" | technical |
| `needs_documentation` | 要正式文档(SDS / COA / brochure / datasheet) | technical |
| `needs_shipping_info` | shipping / tracking / delivery 状态 | operational |
| `needs_customization` | 要 custom service / 带 own material 或 spec | commercial |

**evaluation**: set equality —— parser 输出 7 个 flag set 必须 exactly 等于标注 set。

#### Trigger 边界 —— `needs_price` vs `needs_quote`

- `needs_price`:conversational price ASK("how much / cost / 多少钱"),单一数字询问
- `needs_quote`:formal quotation request("send me a quote / 报价"),**或** RFP-quality 结构化 cost 询问(cost breakdown / billing structure / milestone-based billing / additional costs / fee structure)
- 两者**可同时触发**:user 既问 conversational price 又要 quote breakdown 时打 both

**Worked example**:RFI Section "estimated cost / breakdown by phase / milestone-based billing / additional costs" → 单 section 内同时触发 `needs_price`(用户问 cost)和 `needs_quote`(RFP-quality 结构化 cost ASK)。

#### Trigger 边界 —— `needs_protocol` vs `needs_recommendation`

- `needs_protocol`(core flag):用户问 ProMab 解释 **standard workflow / SOP / procedure**(documented procedure description)。措辞:"what's your protocol for X" / "explain the procedure" / "how does the workflow go" / "walk me through your process"
- `needs_recommendation`(aux flag):用户问 ProMab 给 **建议 / 推荐方法 / 替代方案**(expert advice)。措辞:"please advise" / "any suggestions" / "what would you recommend" / "alternative methods for X" / "help me select"

**关键判别**:用户在求**已有 documented 程序的描述**(needs_protocol)还是求**ProMab 专家给出建议**(needs_recommendation)?

**Worked examples**:
- "What is your standard hybridoma fusion protocol?" → `needs_protocol`(求 documented SOP 描述)
- "Do you have any suggestions for alternative methods for selecting the clone?" → `needs_recommendation`(求 expert advice on methodology,即使 ASK 落在 procedural 维度)
- "Help with the selection of the top clone with high affinity" → `needs_recommendation`(求 ProMab 介入做 selection 不是描述 standard SOP)
- "Could you provide the workflow for this CAR-T service?" → `needs_protocol`(直接求 workflow 描述)

**优先 `needs_recommendation` 不双开 `needs_protocol`** 当 ASK 措辞是 advice/suggestion/alternative 类(类似 `needs_comparison` vs `needs_recommendation` 的边界处理)。

#### Precedent —— Always-custom services 列表

ProMab 业务里以下 service line **总是 custom / build-to-spec**(不存在 catalog 现货):

**Cell line / 蛋白制备 services**:
- E. coli / Baculovirus / Mammalian Expression(覆盖 bacterial strain / 重组蛋白 expression)
- Stable Cell Line Development

**Antibody development services**:
- Antibody Production / Recombinant Antibody
- Mouse / Rabbit / Human Monoclonal Antibody Development
- Hybridoma development & Hybridoma Sequencing(注:catalog 鼠 mAb 产品另算 dual-track)

**Cell engineering services**:
- Custom CAR-T Cell Development
- Custom CAR-NK Cell Development
- Custom CAR-Macrophage Cell Development

**Delivery service**:
- mRNA-LNP Gene Delivery service(注:catalog mRNA-LNPs 产品另算 dual-track)

**Cell-based assay services**:
- T Cell Activation & Proliferation Assay
- T Cell Specificity Assay
- Cytokine Release Assay
- Macrophage Polarization Assay
- DC Migration Assay
- Flow Cytometry Services

对这些 service 的任何 ASK(price / timeline / protocol / documentation)**触发 `needs_customization`**,即使文字 surface 没有 "custom / with my own / specific to" 触发词 —— silence resolver 适用,**但需要 specific custom-run engagement signal**(见下方触发细则)。

**理由**:gold label 反映 route-effective understanding —— 漏打 needs_customization 会让 routing 错过 customization 路径。

#### Silence resolver 触发细则 —— engagement signal

silence resolver 触发 `needs_customization` 需要用户消息含 **specific custom-run engagement signal** —— 即用户朝着具体使用 / 具体购买这项 service:

- **1st-person possessive 在 work scope**:"for **my** target / construct / project / product","**our** project","provided **by me**"
- **explicit launch / generation 动词**:"please generate ... / will be used by us / start the project"
- **具体 quantity / scale / case**:"one or two strains" / "18-21 patients" / "from this specific antigen"

**不**触发 `needs_customization` 的情况:abstract service RFI / capability survey,无 specific engagement signal:
- 3rd-person capability 问句:"what kinds / what types / how does it work in general"
- general scope inquiry:"tell me about your service / I want to learn more"

**Worked examples(对照)**:
- ✅ 触发:Q1 "one or two bacterial strains"(specific quantity)/ Q14 "(provided by me)"(specific material)/ Q13 "for my product"(1st-person possessive)/ Q11 "custom targets / custom run"(explicit)
- ❌ 不触发:Q16 "What kinds of stable cell lines can you generate? engineering process? pricing range?"(全 abstract 3rd-person capability questions,无 engagement signal)

#### Two-tier orthogonal —— retrieval primary 选哪个 bucket

routing 层 `needs_customization` 不触发时,**retrieval 层 primary_intent 仍指向 service-level bucket**(因为服务的答案 chunks 仍在 service-related 桶里)。具体选 `customization_request` vs `service_plan_question` 看 engagement:

| Routing engagement | Retrieval primary | 含义 |
|---|---|---|
| ✅ engagement signal 存在,朝向具体 custom run | `customization_request` | specific custom-run scope chunks |
| ❌ engagement signal 缺失,抽象 service RFI / capability survey | `service_plan_question` | service line 结构 / scope / capability overview / platform intro |

**例**:
- Q11/Q12/Q14 等 → `customization_request`(custom-run engagement)
- Q16 → `service_plan_question`(纯 abstract service RFI)

> _Reviewer note_: parser baseline 跑出来 `needs_customization` 大面积漏属于预期信号(parser 缺业务先验),不是 schema 错。

#### Precedent —— Dual-track objects(catalog AND service 双轨)

ProMab 部分对象同时存在 catalog product 和 custom service line —— **不能 silence-resolver 默认 always-custom**,要靠用户 surface frame 判定:

| 对象 | catalog 形态 | custom service 形态 |
|---|---|---|
| **CAR-T / CAR-NK / CAR-M** | catalog CAR cells(直接购买) | Custom CAR-T / CAR-NK / CAR-Macrophage Development |
| **mRNA-LNP** | catalog mRNA-LNPs 产品 | mRNA-LNP Gene Delivery service |
| **Antibodies** | catalog mAbs(SKU / CAT#)| Antibody Production / Recombinant Antibody / Mouse-Rabbit-Human mAb Development |
| **Hybridoma 衍生 mAb** | catalog 鼠 mAb(hybridoma-derived 现货 SKU)| Hybridoma development & Sequencing service |

**Frame 判定**:

- **Product frame** —— "off-the-shelf / catalog / standard / ready-to-use / SKU / CAT#",或问 specific catalog item 的 pricing / availability:
  → **不触发** `needs_customization`
- **Service frame** —— "custom / development / build / workflow / 'for my project' / 'for my product' / 'for my application'",或问 service scope / capability / cost-for-custom-run:
  → **触发** `needs_customization`
- **Silence / 不明 frame** —— 标注人按业务上下文 + 整封邮件主题判断,rationale 显式标记不确定性

**Worked examples**:
- Q7: "off-the-shelf CarT lead time" → product frame → 不触发 needs_customization,primary `timeline_question`
- Q5: "manufacturing CART-cells for Phase I + IND CMC docs" → service frame(manufacturing + clinical + custom)→ 触发 needs_customization
- Q11: "mRNA-LNP for HEK293 with custom targets" → service frame("custom targets / custom run")→ 触发 needs_customization

> _Reviewer note_: parser baseline 跑出来 dual-track 对象 needs_customization 错率较高属于预期信号(parser 难稳定推断 frame)。建议跑 baseline 后看 dual-track confusion 分布,决定 parser 训练数据补 keywords / surface signals。

#### Precedent 适用边界 —— surface override(对 always-custom services)

对 **always-custom services**:用户主动声明对象为 catalog / off-the-shelf / standard / ready-to-use 时(罕见,例如 "standard mAb production package"),**不触发** `needs_customization`。

**理由**:precedent 是 **silence resolver** 不是 **user-meaning overrider** —— 用户措辞 silence 时用业务现实兜底;用户 explicit 反向声明时信用户 frame。纠正/澄清留给 retrieval / generation 阶段处理。

对 **dual-track objects**:frame detection **是默认机制**(见上方 dual-track 段),用户 surface frame 直接决定 needs_customization 是否触发,**不需要 override 概念**。Q7 "off-the-shelf CarT" 在新 schema 下是 dual-track product-frame 判定的标准例子,不是 always-custom 的 override。

### `auxiliary_flags` (list of str, **required**, default `[]`)
9 个 **long-tail** flag,多在 corner case 出现:
- needs_troubleshooting / needs_recommendation / needs_regulatory_info
- needs_availability / needs_comparison / needs_sample
- needs_order_status / needs_invoice / needs_refund_or_cancellation

**字段必填**,没有匹配的 flag 时**显式写 `[]`**。空列表 ≠ 字段缺失:
- `[]` = "标注人已检查,这条 query 无 auxiliary flag" ✅
- 字段缺失 = 数据脏(标注未完成 / 工具 bug / schema 漂移)❌

**不入主 metric**(`routing_accuracy` 只算 7 core flags),但字段必须存在 —— 让 diff 审查 / 数据清洗 / 统计报表语义稳定。

**长尾边界 case** 仍归 `coverage_suite` 主管;held-out 标这些 flag 的目的是给 routing splitter 完整快照,不是评长尾边界。

#### Trigger 边界 —— `needs_comparison` vs `needs_recommendation`

- `needs_comparison` 触发**显式 comparison 句型**:"X vs Y / what is the difference between / which is better / should we choose X or Y and why / compare A and B"
- `needs_recommendation` 触发 **advice 请求**:"please advise / would recommend / what should we do / getting advice"

"还没决定 A 或 B / haven't decided X or Y / whether X or Y" 类语句虽然结构上有两个 option,但 ASK 重点是 advice 不是 comparison —— **优先收进 `needs_recommendation`,不双开**。防止 `needs_comparison` 过宽。

### `source` (string, required)
- `"real_inbox"` —— 真实客户邮件(默认)
- 后续可扩 `"synthetic" / "edge_case" / "regression"`

### `rationale` (string, required)
简洁说明判断理由,引用关键 invariant(dominant ASK / Precedent / 边界处理)。

### `id` (string, required)
命名约定:`heldout_<primary_intent>_<slug>`,`<slug>` 用 query 关键词组合(避免 collision)。

## Evaluation metrics

两层 metric **独立** 计算:

### routing_accuracy (主)
3 项全部命中:
- `route_splitter_flags` set equality
- `dialogue_act` value match
- `needs_human_review` value match

`auxiliary_flags` **不入** 主 metric,但字段必须存在 —— 没有匹配 flag 时显式写 `[]`。

### retrieval_accuracy (副)
- `primary_intent` enum match

两个 score 独立报告。

## 标注 SOP

每条 query 按以下顺序两步独立标:

### Step 1 — 执行控制层(主轴,先标)
1. 用户**实际要哪些动作?** → `route_splitter_flags`(可空集)+ `auxiliary_flags`(必填,无匹配写 `[]`)
2. 这条 query 的**对话姿态?** → `dialogue_act`(inquiry / selection / closing)
3. **需要人工 escalation 吗?** → `needs_human_review`(bool)

### Step 2 — 语义摘要层(副轴,后标)
4. 按下面的决策树标 `primary_intent`(16 enum 选一):

   **(a) 这条 query 含明确 knowledge ASK 吗?**(用户要拿到具体的知识/内容,不是单纯表达意向)
   - **是** → 走**规则 1**:客服回复时,引用**最多核心 chunk** 的 bucket 是哪个? → 选那个 bucket
   - **否**(全是 "interested in / looking for / please contact us / would like to discuss" 这类 intent 表达)→ 走 **Fallback**:客服回复要引的 scope/intro chunk 在哪个 bucket? → 按 Fallback 细则映射

   **(b) Sanity check —— 没用 routing 思维污染:**
   - 不问"系统该 perform 什么"
   - 不问"用户先要解决哪个问题"
   - 只问"哪个知识桶的 chunk 是回答的核心来源"

   **(c) 跟 Step 1 的 routing flags 不要互相对齐**:
   - 例 1(CAR-T):"workflow + fees" → flags `{needs_protocol, needs_price}` / primary `workflow_question`
   - 例 2(LNP B):"interested in custom LNP + recommended protocol" → flags `{needs_customization, needs_protocol}` / primary `workflow_question`(不是 customization_request,因为 "interested in" 是 intent 表达不是 knowledge ASK)
   - 例 3(LNP A):"interested in custom LNP" 单句 → flags `{needs_customization}` / primary `customization_request`(走 Fallback,因为没 knowledge ASK)

### Step 3 — Sanity check
5. 写 `rationale`,**显式分两段**:
   - routing 层判断理由(flags / dialogue_act / human_review 怎么得到)
   - retrieval 层判断理由(为什么是这个 bucket,跟其他相邻 bucket 怎么排除)
6. **检查是否用 routing 思维污染了 primary_intent** —— 重读你写的 retrieval 段,如果出现"该走 / 该执行 / 该 handle / 该回应"这种动作语,改写
7. **不要让两层互相 align** —— routing 字段和 primary_intent 是 orthogonal,跟 single-axis 直觉相反时,以 invariant 为准

## What this schema does NOT do

- 不评 parser **entity binding**(那是 `parser_eval_golden_set.json` 的职责)
- 不评 **retrieval 系统效果 / end-to-end answer quality**(留给真 e2e set,目前不存在);本 set 评的是 retrieval **supervision signal**(parser 给出的 bucket label 对不对),不是 retrieval 系统拉回的 chunk 对不对
- 不评 **taxonomy corner cases**(那是 `parser_coverage_suite.json` 的职责)
- 不评 **secondary intent / multi-topic decomposition** —— 多 ASK 信号走 flag set,不需要 secondary slot

## 三套集分工

| 集 | 文件 | 职责 | schema 复杂度 |
|---|---|---|---|
| **held-out** | `parser_heldout_benchmark.json` | 稳态评 routing 路径 | 中(本 doc) |
| **coverage suite** | `parser_coverage_suite.json` | 边界 / taxonomy 定义题 | 简(primary_intent + rationale) |
| **parser entity binding** | `parser_eval_golden_set.json`(名字误导,实际是 entity binding 评估) | 对象绑定 | 中(primary + entities) |
