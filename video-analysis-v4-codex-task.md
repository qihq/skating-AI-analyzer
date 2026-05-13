# Codex 开发任务清单：花样滑冰 AI 视频分析正确率迭代

## 阶段一目标：建立“无人工标注”的自动评测基线，并增强 T/A/L 关键帧候选检测

---

**Task ID**: P1-01  
**标题**: 新增 T/A/L 关键帧候选检测服务  
**目标**: 系统能基于 pose、motion score 和采样时间，输出 T/A/L 候选帧、置信度和证据。  
**涉及文件/模块**: `backend/app/services/keyframe_candidates.py`，`backend/tests/test_keyframe_candidates.py`  
**输入 / 输出**:  
输入：`pose_data: dict`、`motion_scores: dict`、`analysis_profile: str`、`effective_fps: float`  
输出：`{"T": {...}, "A": {...}, "L": {...}, "quality_flags": []}`  
**具体实现步骤**:  
1. 新建 `keyframe_candidates.py`，实现 `detect_key_frame_candidates()`。  
2. 对 jump profile 计算 COM/髋中心 y 轨迹、脚踝 y 轨迹、膝角变化、motion peak。  
3. T 用“膝角快速伸展 + COM 上升前后 + motion peak”选择。  
4. A 用平滑 COM y 局部最小值选择。  
5. L 用“脚踝回落 + 膝角缓冲 + motion peak”选择。  
6. 每个候选帧输出 `frame_id`、`timestamp`、`confidence`、`evidence`、`warnings`。  
**验收标准**:  
- 单测覆盖正常 jump、缺 pose、低 visibility、T/A/L 顺序异常。  
- `T < A < L` 时输出合法候选；无法判断时输出 warning 而不是抛异常。  
**依赖 Task**: 无

---

**Task ID**: P1-02  
**标题**: 将关键帧候选写入分析流水线  
**目标**: 每次分析完成 biomechanics 后，`bio_data.key_frame_candidates` 中包含自动 T/A/L 候选结果。  
**涉及文件/模块**: `backend/app/routers/analysis.py`，`backend/app/services/biomechanics.py`，`backend/tests/test_analysis_keyframe_candidates.py`  
**输入 / 输出**:  
输入：已有 `pose_data`、`frame_motion_scores`、`sampling_metadata`  
输出：持久化后的 `analysis.bio_data["key_frame_candidates"]`  
**具体实现步骤**:  
1. 在 `process_analysis()` 的 biomechanics 阶段调用 `detect_key_frame_candidates()`。  
2. 将结果写入 `bio_data["key_frame_candidates"]`。  
3. 保留现有 `bio_data["key_frames"]`，不要破坏旧前端字段。  
4. 处理 retry 场景，重跑 biomechanics 时重新生成候选。  
**验收标准**:  
- 完成分析后 API `/api/analysis/{id}` 返回的 `bio_data` 包含 `key_frame_candidates`。  
- 旧的 `key_frames` 字段仍存在。  
**依赖 Task**: P1-01

---

**Task ID**: P1-03  
**标题**: 新增关键帧候选置信度计算函数  
**目标**: T/A/L 候选帧使用统一、可测试的置信度公式，便于后续 prompt 和融合使用。  
**涉及文件/模块**: `backend/app/services/keyframe_candidates.py`，`backend/tests/test_keyframe_confidence.py`  
**输入 / 输出**:  
输入：`motion_peak_score`、`com_velocity_score`、`pose_visibility_score`、`knee_angle_change_score`、`phase_order_score`  
输出：`0.0～1.0` 的 confidence  
**具体实现步骤**:  
1. 实现 `calculate_key_frame_confidence()`.  
2. 使用公式：`0.30 motion + 0.25 com + 0.20 pose + 0.15 knee + 0.10 order`。  
3. 对缺失信号做降权并加入 `warnings`。  
**验收标准**:  
- 单测验证所有输入 clamp 到 `0.0～1.0`。  
- 缺失 pose 时 confidence 不得高于 `0.55`。  
**依赖 Task**: P1-01

---

**Task ID**: P1-04  
**标题**: 新增自动评测指标服务  
**目标**: 系统能在无人工标注情况下计算代理正确率指标。  
**涉及文件/模块**: `backend/app/services/auto_eval.py`，`backend/tests/test_auto_eval.py`  
**输入 / 输出**:  
输入：`bio_data`、`vision_structured`、`frame_motion_scores`、`analysis_profile`  
输出：`auto_eval` 字典，包含顺序合法率、阶段合法性、冲突率、重复运行签名。  
**具体实现步骤**:  
1. 实现 `build_auto_eval_payload()`。  
2. 计算 `key_frame_order_valid`、`phase_sequence_valid`、`high_confidence_conflicts`、`data_quality_flags`。  
3. 根据 `key_frame_candidates` 生成 `key_frame_signature`。  
4. 输出 `auto_eval_version: "v1"`。  
**验收标准**:  
- 单测覆盖合法 T/A/L、非法顺序、缺失候选、视觉阶段冲突。  
- 输出结构稳定，可 JSON 序列化。  
**依赖 Task**: P1-02

---

**Task ID**: P1-05  
**标题**: 将自动评测结果持久化到分析结果  
**目标**: 每次分析完成后，`cross_validation.auto_eval` 中包含自动评测指标。  
**涉及文件/模块**: `backend/app/routers/analysis.py`，`backend/tests/test_analysis_auto_eval.py`  
**输入 / 输出**:  
输入：分析流水线中的 `bio_data`、`vision_structured`、`cross_validation`  
输出：`analysis.cross_validation["auto_eval"]`  
**具体实现步骤**:  
1. 在 vision/cross validation 后调用 `build_auto_eval_payload()`。  
2. 将结果合并到现有 `cross_validation`，不覆盖已有 dual path summary。  
3. 在处理失败时不阻塞报告生成，只写入 warning。  
**验收标准**:  
- 完成分析后 API 返回 `cross_validation.auto_eval`。  
- 原 `cross_validation.agreement_rate` 等字段不丢失。  
**依赖 Task**: P1-04

---

## 阶段二目标：将视觉 prompt 升级为结构化花样滑冰专项模板，并让输出支持自动校验

---

**Task ID**: P2-01  
**标题**: 新建花样滑冰专项 Prompt 模板模块  
**目标**: Path A / 通用 vision 调用可复用结构化 prompt，包含儿童 Free Skate 1 约束和 T/A/L 候选证据。  
**涉及文件/模块**: `backend/app/services/vision_prompt_templates.py`，`backend/tests/test_vision_prompt_templates.py`  
**输入 / 输出**:  
输入：`action_type`、`action_subtype`、`analysis_profile`、`candidate_key_frames`、`motion_features`、`biomechanics`、`profile_evidence`  
输出：`system_prompt: str`、`user_prompt: str`  
**具体实现步骤**:  
1. 新建 `build_specialized_vision_prompt()`。  
2. 模板必须包含以下内容：  

```text
你是一名专业花样滑冰技术分析师，熟悉 ISU 技术要素、儿童初级训练动作和基础运动生物力学。

当前任务不是正式裁判评分，而是家用训练视频分析。请特别注意：
- 学员是儿童，动作幅度可能小。
- 视频可能是侧面、斜角、远距离或低清晰度。
- 如果脚踝、冰刀或入跳弧线不可见，不要强行判断刃型。
- 如果证据不足，请输出“不可判断”并降低 confidence。
- 必须只输出 JSON。

【动作信息】
action_type: {{action_type}}
action_subtype: {{action_subtype}}
analysis_profile: {{analysis_profile}}
skater_level: Free Skate 1

【后端自动关键帧候选】
candidate_key_frames:
{{candidate_key_frames_json}}

【运动与姿态证据】
motion_features:
{{motion_features_json}}

biomechanics:
{{biomechanics_json}}

【分析步骤】
1. 判断画面质量：good / partial / poor。
2. 判断拍摄角度：front / side / diagonal_front / diagonal_back / unknown。
3. 对每帧判断阶段。
4. 对 T/A/L 候选帧给出 agree / shifted / disagree / unavailable。
5. 对儿童训练水平做保守判断，不使用成人竞技标准。
6. 输出低置信度原因，不要编造不可见细节。

【输出 JSON】
{
  "data_quality_hint": "good|partial|poor",
  "camera_view": "front|side|diagonal_front|diagonal_back|unknown",
  "camera_view_confidence": 0.0,
  "frame_analysis": [
    {
      "frame_id": "frame_0001",
      "phase": "准备|起跳|腾空|落冰|滑出|旋转入|旋转中|旋转出|步法|不可分析",
      "phase_confidence": 0.0,
      "key_frame_agreement": "T|A|L|none|shifted|disagree|unavailable",
      "observations": {
        "knee_bend": "充分|不足|过度|不可判断|不适用",
        "arm_position": "正确|偏高|偏低|不对称|不可判断|不适用",
        "axis_alignment": "垂直|前倾|后仰|侧倾|不可判断|不适用",
        "blade_edge": "外刃|内刃|平刃|不可判断|不适用",
        "landing_absorption": "良好|不足|过度|不可判断|不适用"
      },
      "issues": [],
      "positives": [],
      "confidence": 0.0
    }
  ],
  "action_phase_summary": {
    "detected_phases": [],
    "weakest_phase": "",
    "strongest_phase": "",
    "key_frame_agreement": {
      "T": "agree|shifted|disagree|unavailable",
      "A": "agree|shifted|disagree|unavailable",
      "L": "agree|shifted|disagree|unavailable"
    }
  },
  "overall_raw_text": "2-3句中文总结"
}
```

3. 添加 jump profile 补充规则：刃型不可见时 `blade_edge=不可判断` 且 `element_confidence<=0.55`。  
**验收标准**:  
- 单测确认 prompt 中包含 `candidate_key_frames`、`Free Skate 1`、`不可判断`、JSON schema。  
- 输出不依赖数据库，可独立调用。  
**依赖 Task**: P1-02

---

**Task ID**: P2-02  
**标题**: 将 Path A prompt 切换到专项模板  
**目标**: `vision_path_a.py` 使用新模板，并向模型传入关键帧候选和生物力学证据。  
**涉及文件/模块**: `backend/app/services/vision_path_a.py`，`backend/app/services/vision_dual.py`，`backend/tests/test_vision_path_a_prompt.py`  
**输入 / 输出**:  
输入：Path A 原有参数 + `bio_data` + `frame_motion_scores`  
输出：模型请求中的 user prompt 包含专项模板。  
**具体实现步骤**:  
1. 扩展 `analyze_path_a()` 参数，加入 `bio_data`、`motion_features`。  
2. 在 `vision_dual.py` 调用 Path A 时传入 `bio_data` 和 `frame_motion_scores` 摘要。  
3. 删除或保留旧 `_build_user_prompt()` 作为 fallback，但默认走新模板。  
**验收标准**:  
- 单测 mock provider，断言请求 prompt 包含 `candidate_key_frames`。  
- Path A 返回 schema 仍兼容 `normalize_vision_payload()`。  
**依赖 Task**: P2-01

---

**Task ID**: P2-03  
**标题**: 将通用 vision.py prompt 切换到专项模板  
**目标**: 非 dual path 或 fallback frame mode 也使用同一套结构化专项 prompt。  
**涉及文件/模块**: `backend/app/services/vision.py`，`backend/tests/test_vision_specialized_prompt.py`  
**输入 / 输出**:  
输入：`analyze_frames()` 原有参数 + 可选 `bio_data`、`motion_features`  
输出：多模型视觉调用使用专项 prompt。  
**具体实现步骤**:  
1. 扩展 `analyze_frames()` 可选参数，不破坏旧调用。  
2. 如果未传 `bio_data`，模板中对应字段传 `{}`。  
3. 保留 video mode 的 `phase_segments` 要求。  
**验收标准**:  
- 旧测试继续通过。  
- 新测试确认 frame mode 和 video mode prompt 都包含儿童保守判断规则。  
**依赖 Task**: P2-01

---

**Task ID**: P2-04  
**标题**: 增强视觉输出 normalize，保留 camera 和 key_frame_agreement 字段  
**目标**: 模型输出中的 `camera_view`、`phase_confidence`、`key_frame_agreement` 不再被 normalize 丢弃。  
**涉及文件/模块**: `backend/app/services/vision.py`，`backend/tests/test_vision_normalize_extended_fields.py`  
**输入 / 输出**:  
输入：模型原始 JSON  
输出：标准化后的 `vision_structured` 保留新增字段。  
**具体实现步骤**:  
1. 在 `normalize_vision_payload()` 中保留顶层 `camera_view`、`camera_view_confidence`、`data_quality_hint`。  
2. 在每帧中保留 `phase_confidence`、`key_frame_agreement`。  
3. 对非法枚举降级为 `unknown` 或 `unavailable`。  
**验收标准**:  
- 单测确认新增字段不会丢失。  
- 非法 camera enum 被规范化。  
**依赖 Task**: P2-01

---

**Task ID**: P2-05  
**标题**: 新增视觉 JSON 自动质量校验  
**目标**: 每个模型输出都有 schema 合法性、字段完整度和高风险判断检查。  
**涉及文件/模块**: `backend/app/services/vision_quality.py`，`backend/tests/test_vision_quality.py`  
**输入 / 输出**:  
输入：`vision_payload: dict`  
输出：`{"json_validity_factor": float, "warnings": [], "schema_completeness": float}`  
**具体实现步骤**:  
1. 新建 `evaluate_vision_payload_quality()`。  
2. 检查 `frame_analysis`、`phase`、`confidence`、`data_quality_hint`。  
3. 如果 `data_quality_hint=poor` 且 `blade_edge` 高置信细分，则加入 warning 并降权。  
**验收标准**:  
- poor 画质下强判刃型会产生 warning。  
- 缺少 frame_analysis 时 `json_validity_factor <= 0.3`。  
**依赖 Task**: P2-04

---

## 阶段三目标：从简单投票升级为置信度加权、专项路由和冲突诊断

---

**Task ID**: P3-01  
**标题**: 新增 provider 专项能力配置  
**目标**: 后端可读取每个模型在时序、姿态、儿童动作、JSON 稳定性上的基础权重。  
**涉及文件/模块**: `backend/app/configs/provider_specialties.json`，`backend/app/services/provider_specialties.py`，`backend/tests/test_provider_specialties.py`  
**输入 / 输出**:  
输入：provider 名称，如 `qwen`、`doubao`、`deepseek`、`minimax`  
输出：专项权重 dict  
**具体实现步骤**:  
1. 新建配置文件，默认包含：`frame_phase_weight`、`video_temporal_weight`、`jump_subtype_weight`、`blade_edge_weight`、`child_motion_weight`、`json_reliability_weight`。  
2. 新建 `load_provider_specialty()`。  
3. 未配置 provider 返回保守默认权重。  
**验收标准**:  
- 单测验证四类 provider 均可读取。  
- 配置缺失时不抛异常。  
**依赖 Task**: 无

---

**Task ID**: P3-02  
**标题**: 新增加权融合服务  
**目标**: 多模型结果按置信度、专项权重、JSON 质量和规则一致性融合。  
**涉及文件/模块**: `backend/app/services/vision_fusion.py`，`backend/tests/test_vision_fusion.py`  
**输入 / 输出**:  
输入：`model_results: list[dict]`、`bio_data`、`analysis_profile`  
输出：`fusion_payload`，包含 `final_frame_analysis`、`model_results`、`fusion_decisions`、`conflict_level`。  
**具体实现步骤**:  
1. 实现 `fuse_vision_results_weighted()`。  
2. 权重公式：  

```text
effective_weight =
  provider_base_weight
  * model_confidence
  * json_validity_factor
  * data_quality_factor
  * specialty_factor
  * rule_consistency_factor
  * repeatability_factor
```

3. 每帧 phase 使用加权分数选 final。  
4. 输出每帧候选分数和最终决策证据。  
**验收标准**:  
- 单测覆盖一致、多模型冲突、低质量 JSON、规则冲突降权。  
- 输出 `fusion_version="v3_weighted_router"`。  
**依赖 Task**: P2-05, P3-01

---

**Task ID**: P3-03  
**标题**: 在 vision.py 中接入加权融合  
**目标**: 多 provider frame/video 结果不再只做简单投票，而是默认走加权融合。  
**涉及文件/模块**: `backend/app/services/vision.py`，`backend/tests/test_vision_weighted_fusion_integration.py`  
**输入 / 输出**:  
输入：多个 provider 的 normalized vision payload  
输出：`vision_structured` 包含 `fusion_version`、`fusion_decisions`、`vote_metadata`。  
**具体实现步骤**:  
1. 在 `_merge_vision_results()` 或其调用处接入 `fuse_vision_results_weighted()`。  
2. 保留旧 `phase_votes` 字段用于兼容。  
3. 失败时 fallback 到旧投票逻辑。  
**验收标准**:  
- 旧投票相关测试不破。  
- 新结果包含 `fusion_decisions`。  
**依赖 Task**: P3-02

---

**Task ID**: P3-04  
**标题**: 扩展 dual path cross validation 输出融合诊断  
**目标**: `cross_validation` 中展示 Path A、Path B 和加权融合的冲突等级与降权原因。  
**涉及文件/模块**: `backend/app/services/cross_validator.py`，`backend/app/services/vision_dual.py`，`backend/tests/test_cross_validation_fusion_diagnostics.py`  
**输入 / 输出**:  
输入：Path A、Path B、fusion payload  
输出：`cross_validation.fusion_diagnostics`  
**具体实现步骤**:  
1. 在 `dual_path_summary()` 中加入 `conflict_level`、`downgraded_reasons`、`needs_human_review`。  
2. 如果 high conflict 或关键帧顺序非法，设置 `needs_human_review=true`。  
3. 不阻塞报告生成。  
**验收标准**:  
- 高冲突样本输出 `needs_human_review=true`。  
- Path B 失败时仍能输出诊断。  
**依赖 Task**: P3-02

---

**Task ID**: P3-05  
**标题**: 新增阶段状态机一致性校验  
**目标**: jump/spin/step/spiral 的阶段序列必须符合动作时序，不合法时自动标记或修正。  
**涉及文件/模块**: `backend/app/services/phase_smoother.py`，`backend/tests/test_phase_state_machine_quality.py`  
**输入 / 输出**:  
输入：`frame_analysis`、`analysis_profile`、`bio_data`  
输出：修正后的 `frame_analysis` + `phase_consistency_flags`  
**具体实现步骤**:  
1. 保留现有 `smooth_phases()`，新增一致性评分函数。  
2. 对 jump 强制检查 `准备→起跳→腾空→落冰→滑出`。  
3. 对非法倒退阶段添加 `phase_corrected` 和原因。  
**验收标准**:  
- 单测覆盖落冰出现在起跳前、腾空缺失、spin 阶段倒退。  
- 输出修正原因。  
**依赖 Task**: P1-02

---

**Task ID**: P3-06  
**标题**: 前端家长模式展示融合诊断摘要  
**目标**: 报告页家长模式能看到数据质量、冲突等级、是否建议复查。  
**涉及文件/模块**: `frontend/src/api/client.ts`，`frontend/src/pages/ReportPage.tsx`，`frontend/src/components/AnalysisQualityPanel.tsx`  
**输入 / 输出**:  
输入：`analysis.cross_validation`、`analysis.vision_structured`、`analysis.bio_data`  
输出：报告页新增质量诊断面板。  
**具体实现步骤**:  
1. 新增 `AnalysisQualityPanel`。  
2. 展示 `data_quality_hint`、`conflict_level`、`needs_human_review`、`key_frame_order_valid`。  
3. 仅家长模式显示。  
**验收标准**:  
- completed 报告页家长模式显示质量诊断。  
- 儿童模式不显示复杂诊断。  
**依赖 Task**: P1-05, P3-04

---

## 阶段四目标：建立无人工标注的持续改进闭环、回放评测和长期稳定性跟踪

---

**Task ID**: P4-01  
**标题**: 新增自动评测快照导出接口  
**目标**: 可导出历史分析的自动评测特征，用于 prompt/fusion 版本回放比较。  
**涉及文件/模块**: `backend/app/routers/analysis.py`，`backend/app/schemas.py`，`backend/tests/test_auto_eval_export_api.py`  
**输入 / 输出**:  
输入：查询参数 `limit`、`analysis_profile`、`action_type`  
输出：分析 ID、版本、auto_eval、key_frame_candidates、fusion diagnostics 摘要列表。  
**具体实现步骤**:  
1. 新增 GET `/api/analysis/auto-eval/snapshots`。  
2. 只返回 JSON 摘要，不返回图片或视频。  
3. 按 created_at 倒序，默认 limit=50。  
**验收标准**:  
- API 可返回 completed 分析的自动评测摘要。  
- 无数据时返回空列表。  
**依赖 Task**: P1-05

---

**Task ID**: P4-02  
**标题**: 新增自动回放评测脚本  
**目标**: 可以在本地/NAS 容器内对历史分析快照计算版本对比指标。  
**涉及文件/模块**: `scripts/replay-auto-eval.py`，`backend/tests/test_replay_auto_eval_script.py`  
**输入 / 输出**:  
输入：导出的 snapshots JSON 文件  
输出：`accuracy_proxy_delta`、退化样本列表、冲突率变化。  
**具体实现步骤**:  
1. 新建脚本读取 snapshots。  
2. 统计 `key_frame_order_valid`、`phase_sequence_valid`、`high_confidence_conflicts`。  
3. 输出 Markdown 或 JSON 汇总。  
**验收标准**:  
- 脚本可用示例 JSON 运行。  
- 输出包含退化样本 ID。  
**依赖 Task**: P4-01

---

**Task ID**: P4-03  
**标题**: 新增 provider 自动指标统计服务  
**目标**: 系统能按 provider 统计 JSON 合法率、冲突率、平均置信度和失败率。  
**涉及文件/模块**: `backend/app/services/provider_metrics.py`，`backend/tests/test_provider_metrics.py`  
**输入 / 输出**:  
输入：历史 `vision_structured` / `cross_validation` 列表  
输出：provider metrics dict  
**具体实现步骤**:  
1. 实现 `summarize_provider_metrics()`。  
2. 统计 `json_valid_rate`、`avg_effective_weight`、`conflict_rate`、`failure_rate`。  
3. 生成权重调整建议，但不自动改配置。  
**验收标准**:  
- 单测覆盖无 provider、单 provider、多 provider。  
- 输出可 JSON 序列化。  
**依赖 Task**: P3-03

---

**Task ID**: P4-04  
**标题**: 新增 provider 指标查询接口  
**目标**: 前端或维护者可查看各模型近期表现，辅助手动调权。  
**涉及文件/模块**: `backend/app/routers/providers.py`，`backend/app/schemas.py`，`backend/tests/test_provider_metrics_api.py`  
**输入 / 输出**:  
输入：查询参数 `days`、`analysis_profile`  
输出：provider 指标列表。  
**具体实现步骤**:  
1. 新增 GET `/api/providers/metrics`。  
2. 从最近 completed analyses 聚合数据。  
3. 返回 `ProviderMetricPublic` schema。  
**验收标准**:  
- API 返回 provider 指标。  
- 没有历史数据时返回空数组。  
**依赖 Task**: P4-03

---

**Task ID**: P4-05  
**标题**: 新增低质量视频保守策略  
**目标**: poor/partial 视频下系统减少高置信度细节判断，尤其是刃型和跳跃种类。  
**涉及文件/模块**: `backend/app/services/vision_quality.py`，`backend/app/services/report.py`，`backend/tests/test_low_quality_conservative_policy.py`  
**输入 / 输出**:  
输入：`data_quality_hint`、`camera_view`、`pose_visibility`、`vision_payload`  
输出：降权后的视觉 payload 或 report quality flags。  
**具体实现步骤**:  
1. 在 `vision_quality.py` 实现 `apply_low_quality_policy()`。  
2. poor 质量下将 blade_edge 细分改为 `不可判断`。  
3. poor 质量下高置信 element 判断降到 `<=0.55`。  
4. report 生成时加入保守提示。  
**验收标准**:  
- poor 质量样本不会输出高置信刃型判断。  
- 报告中出现“视频质量有限，建议保守解读”。  
**依赖 Task**: P2-05

---

**Task ID**: P4-06  
**标题**: 前端展示自动评测与回放入口  
**目标**: 设置或 API 管理页面可查看 provider 指标和自动评测快照摘要。  
**涉及文件/模块**: `frontend/src/api/client.ts`，`frontend/src/pages/ApiSettingsPage.tsx`，`frontend/src/components/ProviderMetricsPanel.tsx`  
**输入 / 输出**:  
输入：`/api/providers/metrics`、`/api/analysis/auto-eval/snapshots`  
输出：前端展示 provider 指标、冲突率、JSON 合法率。  
**具体实现步骤**:  
1. 在 `client.ts` 增加 fetch 函数和 TypeScript 类型。  
2. 新建 `ProviderMetricsPanel`。  
3. 在 `ApiSettingsPage` 家长/维护视图展示。  
**验收标准**:  
- 页面能看到 provider 指标列表。  
- API 失败时显示轻量错误状态。  
**依赖 Task**: P4-01, P4-04

---

## 依赖关系表

| Task ID | 依赖 Task ID |
|---|---|
| P1-01 | 无 |
| P1-02 | P1-01 |
| P1-03 | P1-01 |
| P1-04 | P1-02 |
| P1-05 | P1-04 |
| P2-01 | P1-02 |
| P2-02 | P2-01 |
| P2-03 | P2-01 |
| P2-04 | P2-01 |
| P2-05 | P2-04 |
| P3-01 | 无 |
| P3-02 | P2-05, P3-01 |
| P3-03 | P3-02 |
| P3-04 | P3-02 |
| P3-05 | P1-02 |
| P3-06 | P1-05, P3-04 |
| P4-01 | P1-05 |
| P4-02 | P4-01 |
| P4-03 | P3-03 |
| P4-04 | P4-03 |
| P4-05 | P2-05 |
| P4-06 | P4-01, P4-04 |
