from __future__ import annotations

from pathlib import Path

import pandas as pd


PRIORITY_MAP = {
    "9.1": "P0",
    "9.2": "P0",
    "8.7": "P1",
    "8.8": "P1",
    "8.9": "P1",
    "8.10": "P1",
    "9.5": "P1",
    "9.7": "P1",
    "8.3": "P2",
    "8.5": "P2",
    "9.3": "P2",
    "9.4": "P2",
    "9.6": "P2",
}

STAGE_TEMPLATES = [
    ("Clarify", "规则澄清", "明确需求边界、判定口径与数据结构输出"),
    ("Implement", "代码实现", "在核心模块中实现功能并补齐必要接口"),
    ("Test", "测试验证", "补充单元/集成测试并验证边界与回归"),
    ("Doc", "文档更新", "更新说明文档与使用示例，沉淀实现约束"),
]

HOURS_BY_PRIORITY = {
    "P0": {"Clarify": 1.5, "Implement": 6.0, "Test": 2.0, "Doc": 1.0},
    "P1": {"Clarify": 1.0, "Implement": 4.0, "Test": 1.5, "Doc": 0.5},
    "P2": {"Clarify": 0.5, "Implement": 3.0, "Test": 1.0, "Doc": 0.5},
}


def _normalize_req_id(val: object) -> str:
    s = str(val).strip()
    return s


def _build_acceptance(stage: str, req_id: str, req_text: str) -> str:
    if stage == "Clarify":
        return f"形成{req_id}的可执行判定清单，覆盖输入/输出与边界场景。"
    if stage == "Implement":
        return f"{req_id}对应逻辑已落地，核心路径可运行且不破坏现有功能。"
    if stage == "Test":
        return f"{req_id}新增测试通过，关键边界与回归用例覆盖到位。"
    return f"{req_id}实现说明已更新，包含变更点、限制与示例。"


def main() -> None:
    docs_dir = Path(__file__).resolve().parent
    src = docs_dir / "zhongshu_trend_requirements_analysis.xlsx"
    out = docs_dir / "zhongshu_trend_subtasks_plan.xlsx"

    df = pd.read_excel(src, sheet_name="中枢与走势需求评估")
    needed = df[df["当前状态"].isin(["部分实现", "未实现"])].copy()
    needed["编号"] = needed["编号"].map(_normalize_req_id)

    rows: list[dict[str, object]] = []
    task_seq = 1

    for _, r in needed.iterrows():
        req_id = str(r["编号"]).strip()
        req_text = str(r["需求条目"]).strip()
        gap = str(r.get("缺口/风险", "")).strip()
        priority = PRIORITY_MAP.get(req_id, str(r.get("建议优先级", "P2")).strip() or "P2")

        task_ids: dict[str, str] = {}
        for stage, stage_cn, stage_desc in STAGE_TEMPLATES:
            task_id = f"T{task_seq:03d}"
            task_ids[stage] = task_id
            task_seq += 1

            if stage == "Clarify":
                dep = "-"
            elif stage == "Implement":
                dep = task_ids["Clarify"]
            elif stage == "Test":
                dep = task_ids["Implement"]
            else:
                dep = task_ids["Implement"]

            subtask = f"[{req_id}] {stage_cn}: {req_text}"
            acceptance = _build_acceptance(stage, req_id, req_text)
            est = HOURS_BY_PRIORITY.get(priority, HOURS_BY_PRIORITY["P2"])[stage]

            rows.append(
                {
                    "任务ID": task_id,
                    "需求ID": req_id,
                    "阶段": stage,
                    "子任务": subtask,
                    "依赖": dep,
                    "优先级": priority,
                    "工时(小时)": est,
                    "验收标准": acceptance,
                    "状态": "Pending",
                    "备注": stage_desc if not gap else f"{stage_desc}；风险: {gap}",
                }
            )

    plan_df = pd.DataFrame(rows)
    summary_priority = plan_df.groupby("优先级", as_index=False).size().rename(columns={"size": "任务数"})
    summary_stage = plan_df.groupby("阶段", as_index=False).size().rename(columns={"size": "任务数"})

    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        plan_df.to_excel(writer, sheet_name="子任务计划", index=False)
        summary_priority.to_excel(writer, sheet_name="汇总", index=False, startrow=0)
        summary_stage.to_excel(writer, sheet_name="汇总", index=False, startrow=len(summary_priority) + 3)

    print(f"Generated: {out}")
    print(f"Total tasks: {len(plan_df)}")


if __name__ == "__main__":
    main()
