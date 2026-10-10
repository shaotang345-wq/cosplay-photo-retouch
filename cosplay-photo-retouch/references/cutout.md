# 合并的 Windows 本地抠图模块

## 搜索来源
2026-10-08 找到 [remove-bg](https://github.com/ziyu/useful-skills/blob/main/remove-bg/SKILL.md) 和 [rembg-bg-removal](https://github.com/OpenGHz/rembg-bg-removal)。前者使用 uv/rembg，后者主要为 Linux Bash。它们的仓库分别为 0、1 星，安装量未能核实，不把第三方安装脚本直接当作成熟 Windows 后端执行。

合并本地推理、隔离环境、模型缓存及蒙版工作流；Windows 包装代码为新写，未复制第三方技能文件。底层直接使用 [rembg 官方项目](https://github.com/danielgatis/rembg) 和 Python 接口。原项目约 25k 星，代码 MIT；模型权重遵循各自许可。

## 已实现能力
`scripts/cutout.py` 使用人工同尺寸蒙版或 rembg CPU 模型，生成候选 alpha、透明前景、保守保护区、背景可编辑区域及报告。画布、人物位置不变，透明前景的每个 RGB 像素（包括透明区）严格来自原图。只改变 alpha，不采用模型输出的 RGB 或颜色去污染。sRGB IEC61966-2.1 配置原样保留；其他 ICC、方向不为 1、RAW/16-bit 均拒绝。

自动模型内部会缩放来估计蒙版，再返回原尺寸蒙版；这不代表发丝、半透明边缘可以强保证。原图 RGB 没有缩小再放大的处理。若用户要求连蒙版推理也不许缩放，只能使用人工原尺寸蒙版。

透明前景是抠图素材，其 alpha 有意变化，不是符合原照片 alpha 锁的成片。照片修图仍用 retouch.py 原始底图，换背景仍独立审批。不能将抠图素材替换原底图绕过人物保护。

## 快速流程
在粗预览/整体方案中一起核对发丝、衣服、道具、薄纱，不增加单独泛泛确认。未经确认的 AI 蒙版只能称候选；确认后用于项目保护。已有人工保护蒙版用 --keep 合并，不能因模型漏检缩小保护范围；keep 非零像素也保留原 alpha，避免道具被切掉。默认保护边界扩展 12 原生像素。

同一原图、模型版本、权重哈希的蒙版复用缓存。第一轮权重下载与环境安装较慢，后续不重复下载。u2netp 用作快速候选，不保证复杂假发质量；birefnet-portrait/general-lite 是可选路线，须另下载权重，只能将实际运行的模型标为本机已测试。

## Windows 使用
可选依赖不影响基础调色。Python 3.11–3.13，已测试版本见抠图运行报告。独立环境默认位于 CODEX_HOME\skill-envs\cosplay-cutout，未设置时为当前用户 .codex 下同一路径。

```powershell
py -3.12 -m venv "$env:USERPROFILE\.codex\skill-envs\cosplay-cutout"
$taskCutoutPython = "$env:USERPROFILE\.codex\skill-envs\cosplay-cutout\Scripts\python.exe"
& $taskCutoutPython -m pip install -r 'C:\path\to\cosplay-photo-retouch\requirements-cutout.txt'
& $taskCutoutPython 'C:\path\to\cosplay-photo-retouch\scripts\cutout.py' --input 'D:\photos\source.jpg' --output-dir 'D:\photos\candidate01' --model u2netp --keep 'D:\photos\existing-protect.png'
# 完全不使用 AI 的人工蒙版模式，只需基础 Pillow/NumPy
& $taskCutoutPython 'C:\path\to\scripts\cutout.py' --input 'D:\photos\source.jpg' --mask 'D:\photos\alpha.png' --output-dir 'D:\photos\candidate02'
```

输出目录必须是新目录，不覆盖任何原件。候选不是成片；需检查边缘后采用。脚本没有云服务或 Photoshop 接口，不开放 HTTP 服务。模型缓存在隔离环境 models 下，可用 --model-cache 指定。
