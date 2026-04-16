"""
ProMab RAG 知识库邮件知识提取流水线

单遍处理方式：每封邮件在一次 LLM 调用中同时完成分类和提取。
若邮件不含可复用知识，LLM 返回空列表，无需单独的过滤步骤。

用法：
    python -m src.rag.email_knowledge_extraction \
        --input sample_responses2.csv \
        --output rag_facts.jsonl \
        [--model claude-opus-4-6] \
        [--dry-run]

输出的 JSONL 文件可直接传入 facts_to_ingestion_sections()，
生成可导入向量数据库的 IngestionSection 对象。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# 提取提示词
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
你是 ProMab Biotechnologies 的知识库整理员。ProMab 是一家合同研究机构（CRO），专注于：
- 定制抗体开发（多克隆、单克隆、重组、纳米抗体）
- CAR-T / CAR-NK 细胞治疗开发及慢病毒生产
- 蛋白质表达与纯化（大肠杆菌、杆状病毒、哺乳动物、酵母系统）
- 定制检测方法开发（ELISA、流式细胞术、IHC 等）
- mRNA / LNP 开发

你的任务：阅读一封邮件正文，提取所有可复用的知识点，以帮助 AI 助手回答客户的未来问题。
只输出 JSON 数组，不要输出其他任何内容。
若邮件不含任何面向客户的可复用知识，输出空数组：[]

──────────────────────────────────────────────────
知识分类
──────────────────────────────────────────────────

提取属于以下一个或多个分类的知识点：

1. service_capability（服务能力）
   ProMab 能做或不能做的事项，包括服务范围、交付物、技术限制。
   示例：
   - "ProMab 提供定制 CAR-T 开发服务，包含完整的 GMP 级慢病毒生产。"
   - "ProMab 目前不在本公司设施内开展体内小鼠实验。"

2. pricing_timeline（价格与周期）
   定价、报价、交货周期、加急费、批量折扣。
   示例：
   - "标准单克隆抗体开发周期为 4–6 个月。"
   - "交付周期不足 8 周的项目需收取加急费。"

3. policy（政策与条款）
   下单要求、退款/返工政策、发货条款、付款条件、文件或知识产权要求、保密协议惯例。
   示例：
   - "ProMab 在转移细胞系之前需要签署 MTA（材料转让协议）。"
   - "若蛋白质 QC 不达标，ProMab 将免费重新表达。"

4. technical_protocol（技术方案）
   具体技术细节：浓度、缓冲液条件、存储要求、推荐检测格式、已验证物种/宿主、已知局限性。
   示例：
   - "抗鼠 IgG 二抗不应用于含鼠血清的样本，会产生交叉反应。"
   - "该抗体用于 ELISA 的最佳包被浓度为 1–2 µg/mL。"

5. product_specification（产品规格）
   命名产品的属性：货号、靶点、宿主物种、同型、已验证应用、交叉反应性、批次特定说明。
   示例：
   - "PM-Ab1234 是兔源抗人 CD19 抗体，已通过流式细胞术验证。"
   - "批次 #LV-0056 经 SEC-HPLC 检测聚集率 <5%。"

──────────────────────────────────────────────────
输出格式 — JSON 数组
──────────────────────────────────────────────────

数组中每个元素必须是包含以下字段的 JSON 对象：

{
  "category": "<上述五个分类键之一>",
  "fact": "<单条独立的知识陈述，使用第三人称，最多 3 句话>",
  "tags": ["<用于检索的关键词标签，例如服务名称、产品、物种、检测类型>"],
  "business_line": "<以下之一：antibody | car_t_car_nk | protein_expression | cell-based assay | mrna_lnp | general>",
  "confidence": <0.0–1.0，你对该知识点准确性和可复用性的置信度>,
  "source_snippet": "<邮件中支持该知识点的原文引用，1–2 句>"
}

规则：
- `fact` 字段须为独立陈述，客户无需看到原始邮件即可理解。
  错误示例："我们可以在下周五之前完成。"
  正确示例："ProMab 可在项目启动后 4 周内交付标准 ELISA 方法开发。"
- 不要提取纯内部运营内容（快递单号、抄送关系、无政策内容的付款收据、日程安排）。
- 不要发明或推断邮件中未明确说明的内容，若不确定请降低置信度。
- 一封邮件可提取 0–6 条跨多个分类的知识点，这是正常情况。
- 若邮件纯属内部运营、垃圾邮件或不含可复用知识，返回 []。
"""

EXTRACTION_USER_TEMPLATE = """\
从以下 ProMab 邮件正文中提取可复用的知识点。
只返回 JSON 数组，不要任何解释，不要 Markdown 代码块。

邮件正文：
{email_body}
"""


# ---------------------------------------------------------------------------
# 转换器：提取的知识点 → IngestionSection
# ---------------------------------------------------------------------------

def facts_to_ingestion_sections(
    facts: list[dict[str, Any]],
    *,
    source_email_index: int | str = "",
) -> list[dict[str, Any]]:
    """
    将原始提取的知识点字典转换为 IngestionSection 兼容对象。
    可直接传入 IngestionSection(**d) 后导入向量数据库。
    """
    from src.rag.ingestion_config import IngestionSection  # 延迟导入，保持模块可独立运行

    sections = []
    for f in facts:
        category = f.get("category", "general")
        fact_text = f.get("fact", "").strip()
        if not fact_text:
            continue

        title = _category_title(category, f)
        tags = list(f.get("tags") or [])
        # 补充分类和业务线标签
        for extra in [category, f.get("business_line", "")]:
            if extra and extra not in tags:
                tags.append(extra)

        section = IngestionSection(
            company="ProMab",
            title=title,
            body=fact_text,
            section_type="email_knowledge",
            tags=tags,
            source_path=f"email_index:{source_email_index}",
            business_line=f.get("business_line", "general"),
            structural_tag="fact",
        )
        sections.append(section)
    return sections


def _category_title(category: str, fact: dict[str, Any]) -> str:
    prefixes = {
        "service_capability": "服务能力",
        "pricing_timeline": "价格与周期",
        "policy": "政策与条款",
        "technical_protocol": "技术方案",
        "product_specification": "产品规格",
    }
    prefix = prefixes.get(category, "知识点")
    tags = fact.get("tags") or []
    suffix = f" — {tags[0]}" if tags else ""
    return f"{prefix}{suffix}"


# ---------------------------------------------------------------------------
# LLM 调用（Anthropic SDK）
# ---------------------------------------------------------------------------

def call_llm(email_body: str, *, model: str = "claude-opus-4-6") -> list[dict[str, Any]]:
    """调用 Claude 从单封邮件正文中提取知识点，返回知识点字典列表。"""
    try:
        import anthropic
    except ImportError:
        raise ImportError("请先安装：pip install anthropic")

    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": EXTRACTION_USER_TEMPLATE.format(email_body=email_body[:6000]),
            }
        ],
    )
    raw = message.content[0].text.strip()

    # 若模型仍然返回了 Markdown 代码块，去除之
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return []

    if not isinstance(result, list):
        return []
    return result


# ---------------------------------------------------------------------------
# 命令行运行器
# ---------------------------------------------------------------------------

def run_extraction(
    input_csv: str,
    output_jsonl: str,
    *,
    model: str = "claude-opus-4-6",
    body_column: str = "body",
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    df = pd.read_csv(input_csv)
    if body_column not in df.columns:
        available = list(df.columns)
        raise ValueError(f"列 '{body_column}' 不存在，可用列：{available}")

    rows = df.iterrows()
    total = len(df)
    if limit:
        import itertools
        rows = itertools.islice(rows, limit)
        total = min(total, limit)

    out_path = Path(output_jsonl)
    extracted_count = 0
    email_count = 0

    with out_path.open("w", encoding="utf-8") as fout:
        for idx, row in rows:
            email_count += 1
            body = str(row.get(body_column, "") or "").strip()
            if not body or len(body) < 30:
                print(f"[{email_count}/{total}] idx={idx} — 已跳过（内容为空）", flush=True)
                continue

            if dry_run:
                print(f"[{email_count}/{total}] idx={idx} — 试运行，正文长度={len(body)}", flush=True)
                continue

            try:
                facts = call_llm(body, model=model)
            except Exception as exc:
                print(f"[{email_count}/{total}] idx={idx} — LLM 错误：{exc}", flush=True)
                facts = []

            if facts:
                record = {"email_index": idx, "facts": facts}
                fout.write(json.dumps(record, ensure_ascii=False) + "\n")
                extracted_count += len(facts)
                print(
                    f"[{email_count}/{total}] idx={idx} — 提取到 {len(facts)} 条知识点",
                    flush=True,
                )
            else:
                print(f"[{email_count}/{total}] idx={idx} — 无可用知识点", flush=True)

    if not dry_run:
        print(f"\n完成。从 {email_count} 封邮件中共提取 {extracted_count} 条知识点 → {out_path}")


# ---------------------------------------------------------------------------
# 程序入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从邮件 CSV 中提取 ProMab RAG 知识库")
    parser.add_argument("--input", default="sample_responses2.csv", help="输入 CSV 文件路径")
    parser.add_argument("--output", default="rag_facts.jsonl", help="输出 JSONL 文件路径")
    parser.add_argument("--model", default="claude-opus-4-6", help="Claude 模型 ID")
    parser.add_argument("--body-column", default="body", help="包含邮件正文的 CSV 列名")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 封邮件（用于测试）")
    parser.add_argument("--dry-run", action="store_true", help="仅显示将处理的内容，不调用 LLM")
    args = parser.parse_args()

    run_extraction(
        args.input,
        args.output,
        model=args.model,
        body_column=args.body_column,
        dry_run=args.dry_run,
        limit=args.limit,
    )
