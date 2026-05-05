# 线段特征序列实现说明（对应 ST001-ST016）

本文件用于记录线段任务 ST001-ST016 的规则口径、代码实现与验证映射。

## 章节映射

- 第67课：线段划分工具“特征序列”定义。
- 第77课、第78课：线段延伸与破坏的后续规则（本批次仅覆盖特征序列定义基础）。

## 本批次已完成范围

1. 向上线段特征序列定义：取线段中的向下笔。
2. 向下线段特征序列定义：取线段中的向上笔。
3. 向下线段特征序列元素高低点反向定义：`high <- pen.low`, `low <- pen.high`。
4. 特征序列 S 的时间顺序：按笔在序列中的时间顺序输出。

5. 特征序列包含关系处理（对应 ST017-ST032）：
  - 从左到右处理相邻元素；
  - 若存在包含关系则合并；
  - 向上线段合并规则：high=max, low=min；
  - 向下线段合并规则：high=min, low=max（反向）；
  - 合并后继续检查，直到无包含关系为止。

6. 线段破坏确认（对应 ST033-ST048）：
  - 反向特征序列分型识别（基于三元素局部极值）；
  - 前两元素缺口判定（无重叠即缺口）；
  - 第一类破坏：首个反向分型出现且前两元素无缺口，立即确认；
  - 第一类破坏端点：结束点与新起点即该首个分型顶点；
  - 第二类破坏：若前两元素有缺口，则等待后续反向分型确认；
  - 第二类破坏端点：确认后结束点与新起点仍回到“最初分型顶点”。

7. 线段延伸与未完成输出（对应 ST049-ST080）：
  - 主流程保持贪心延伸，确认到最远有效终点后再切分；
  - 允许保留尾部未完成线段，`is_complete=False`；
  - 尾段输出支持结构化记录，便于 GUI/导出/回测复用；
  - 线段记录包含 `id/type/start/end/bi_count/bi_ids/is_complete`。

8. 输入输出与代码结构（对应 ST057-ST084）：
  - 输入规范：`bi_list` 作为笔列表输入，兼容现有 `pens` 入口；
  - 输出规范：`build_segment_records(...)` 返回标准化 `segment_list`；
  - 结构化包装器：`SegmentIdentifier` 提供构建、分型、破坏、导出一体化入口；
  - 结构化 API 兼容函数式 API，便于逐步替换旧调用。

9. 示例对齐与约束（对应 ST085-ST100）：
  - 示例场景可通过 `include_incomplete_tail=True` 输出未完成段；
  - 代码不引入自定义破坏规则，仍沿用前述包含/分型/缺口口径；
  - 注释与文档统一标注第67/77/78课相关含义，避免口径漂移。

## 代码落点

- `chancode/xd.py`
  - `FeatureSequenceElement`：特征序列元素结构。
  - `_build_feature_sequence(...)`：构建特征序列 S。
  - `_handle_feature_sequence_include(...)`：包含关系处理主函数。
  - `_merge_feature_elements(...)`：方向化包含合并规则。
  - `_detect_feature_sequence_fractals(...)`：特征序列分型识别。
  - `_has_gap_between_feature_elements(...)`：缺口判断。
  - `assess_segment_break_by_feature_sequence(...)`：两类破坏统一评估入口。
  - `SegmentBreakResult`：破坏确认结果结构（含 anchor/confirm 两类端点信息）。
  - `SegmentIdentifier`：结构化线段识别包装器。
  - `build_segment_records(...)`：输出标准化线段记录。

## 测试落点

- `tests/test_xd.py`
  - `test_feature_sequence_up_uses_down_pens`
  - `test_feature_sequence_down_uses_up_pens_with_reversed_high_low`
  - `test_feature_sequence_keeps_time_order`
  - `test_feature_sequence_include_merge_up_rule_max_min`
  - `test_feature_sequence_include_merge_down_rule_min_max`
  - `test_feature_sequence_include_iterative_until_no_include`
  - `test_first_break_confirmed_without_gap_and_anchor_equals_confirm`
  - `test_second_break_with_gap_waits_for_next_reverse_fractal`
  - `test_second_break_confirmed_but_endpoint_stays_on_initial_anchor`
  - `test_build_segment_records_exports_required_fields`
  - `test_build_segments_can_emit_incomplete_tail`
  - `test_segment_identifier_wrapper_matches_function_api`

## 注意

本批次已覆盖“包含处理 + 分型判定 + 缺口与两类破坏确认”的核心链路；完整线段状态机与延伸重算策略在后续任务继续完善。

当前实现同时覆盖线段延伸、未完成尾段输出与结构化记录导出，足以支撑 ST049-ST100 对应的输入/输出规范与代码结构要求。