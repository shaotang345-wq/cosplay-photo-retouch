---
name: cosplay-photo-retouch
description: Cosplay 摄影修图：原尺寸蒙版调色、候选抠图、独立背景和特效融合、局部迭代及验收导出。保护面部与人物几何，不整图重生成。
---

# Cosplay 摄影修图

这是唯一入口，分析、调色、背景、特效和导出在同一工程执行，不依赖其他 Cosplay Skill。先读一次 [运行协议](references/v3-runtime.md) 与 [偏好](references/user-preferences.md)，同轮复用。执行器为本目录 `scripts/v3.py`，默认 standard；同一工程不并发写。

## 最短工作流

1. `context` 查看原图、已有层、授权与缓存，明确本轮要改和不能改的区域。已有层走 `route/revise`；没有实际变化即停止。新设计才 `plan`。只分析缺失或输入变化的内容，文件哈希绑定缓存。
2. 登记真实授权；已有授权不重复询问，超出范围的换景/重绘/强特效才单独审批。只执行必要操作，不强制串行分析、调色、背景、特效、再调色。纯参数或蒙版修改不调用生成。
3. `run` 后实际看整体与问题位置原生局部，完成 `inspect` 的 intent、space、edges、lighting、effects 五项。失败只修失败部分，保留合格父版；不把数值通过说成美观保证。
4. 门禁全部通过后 `export` 原尺寸 PNG，已有导出授权直接执行。只展示最终成片及链接，不主动展示独立素材或内部预览。版本与 `checkout` 保留，可回退。

## 不可省略的保护

原图不覆盖、不裁剪、不重采样；人物不平移、缩放、旋转或改变姿态、配饰形状。冻结面部，任何特效不得覆盖脸。禁止整张原片生成后冒充原人物合成。背景素材缩放必须有明确授权并记入项目。

前景特效可在美观时覆盖非面部的获准区域，但必须登记 face/foreground 蒙版，不能靠提示词代替保护。窄边缘按材质适度羽化 alpha，保留发丝和薄纱；不得模糊整个人物 RGB。有限局部补光与边缘修补遵守实际授权，不能扩展为人物重绘。

局部修改用实际局部蒙版；不能调整全层 opacity 后声称另一侧未变。跨项目特效不直接复用，先核对角色、场景、光照、尺度和用途。生成前登记预算，结果后记录真实调用；失败和新计划不重置预算。

## 按需操作

- 调色：蒙版曝光、对比、饱和度、gamma、RGB gains；不追加无关磨皮或锐化。参数见 [契约](references/contracts.md)。
- 抠图：按 [抠图](references/cutout.md) 获取候选蒙版，实际确认覆盖和边缘。自动候选不是验收通过。
- 背景：先判断净化原背景是否足够；换景见 [场景融合](references/scene-integration.md)。仅需窄边缘修补时读 [备用融合](references/fallback-fusion.md)。
- 特效：按 [效果规范](references/effects.md) 分离必要的本体、局部辉光、粒子与互动光，不强制六层。对比同底图 Glow 开/关，亮核清楚、远处纹理不被光晕覆盖。未要求不加月亮等醒目天体。
- 新素材：见 [生成](references/generation.md)；动漫转写实只用于背景和独立素材，见 [素材写实](references/material-realism.md)，不转化人物。
- 多参考/材质：见 [摄影分析](references/photographic-analysis.md)，区分观察与推断、去重系列参考；只在需求涉及时展开。

没有内置生成模型、Photoshop/PSD 接口、自动审美或感知清晰度强保证。依赖宿主工具的功能必须先核实可用性。完整限制见 [能力边界](references/limits.md)；旧工程兼容见 [旧流程](references/workflow.md)。
