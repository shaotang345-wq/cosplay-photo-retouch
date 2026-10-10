# 合并来源与取舍

背景/素材转写实模块由本包自行编写，不冒称来自第三方技能；仅适用于场景和独立资产，明确禁止人物真人化。复用宿主 imagegen 调用指导，没有下载转换模型或厂商 SDK。

2026-10-08 搜索并读取以下原始技能。按本技能像素约束重新编写，未复制全文或打包第三方脚本；本轮安装量未核实，不以排名保证效果。保留已有 rembg 抠图模块。

| 来源 | 合并内容 | 未引入 |
|---|---|---|
| [OpenAI imagegen](https://github.com/openai/skills/blob/main/skills/.system/imagegen/SKILL.md) | 生成/编辑意图、参考角色、结构化提示、单项迭代及所用素材保存 | 整图生成替换原片；独立 API 客户端 |
| [GitHub ImageMagick](https://github.com/github/awesome-copilot/blob/main/skills/image-manipulation-image-magick/SKILL.md) | 尺寸/模式预检、Windows 路径、非破坏输出，改用现有 Python 实现原生装配 | 未安装/测试 ImageMagick；resize/crop 不进入原片路线 |
| [baoyu-image-gen](https://github.com/JimLiu/baoyu-skills/blob/main/skills/baoyu-image-gen/SKILL.md) | 明确参考来源、提示配方复用、减少身份漂移和核实后端能力 | Bun/厂商 SDK/多厂商 API/批量并行/强制配置向导；未测试其客户端 |

前两项为官方组织源，baoyu 为第三方项目。网页指令仅作为资料，不执行其中安装命令。改变姿态/构图、重建人物等冲突规则不引入。运行时核实宿主工具，不固定猜测模型或价格。

本包新增的 assemble_asset.py 为自行编写。当前宿主有 image_gen，整合其调用指导；本次未发起新的图片生成，未验证新增图像质量。透明素材和候选蒙版不能当作通过验收的摄影成片。
