> V3 项目使用 [V3 运行协议](v3-runtime.md)，本文保留旧版兼容流程。默认模式为 standard。

# Windows 安装和运行

抠图使用独立可选 CPU 环境，见 [cutout.md](cutout.md)。核心调色不需要 rembg。

Windows 10/11，Python 3.10+，依赖 Pillow 和 NumPy（requirements.txt）。脚本不访问网络、不调用 Photoshop 或 AI 服务。本次实测环境见测试报告，版本范围不等于每个组合都已验证。

解压并保留顶层 cosplay-photo-retouch 文件夹，在该文件夹中用 PowerShell 运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\install.py
```

安装目标默认 CODEX_HOME\skills，未设置时为当前用户 .codex\skills；可用 `--skills-dir 'D:\my-codex\skills'` 指定。安装器备份并更新同名技能，迁出六个旧入口；不复制 .venv。可保留解压目录中的 Python 环境并使用绝对路径，或安装后在目标另建环境。不要分享虚拟环境。

重新打开/刷新 Codex 后用 `$cosplay-photo-retouch` 调用。Work 是否支持本地技能发现依赖宿主；本包没有 Work 插件接口，不宣称已经安装到 Work。技能安装需要宿主允许写目标目录。

## 一次修图
准备原图 source.png、人工确认的 protect.png、背景蒙版 bg.png，尺寸完全相同。原件放在项目目录外。蒙版制作及覆盖确认是人工步骤。

plan.json（素材路径相对 JSON 所在目录）：

```json
{"summary":"仅降低背景饱和度","operations":[{"id":"bg-tone","type":"tone","mask":"bg.png","saturation":0.95}]}
```

```powershell
$taskPython = 'C:\path\to\python.exe'
$taskScript = 'C:\path\to\cosplay-photo-retouch\scripts\retouch.py'
& $taskPython $taskScript --project 'D:\photos\session01' init --original 'D:\photos\source.png' --protected 'D:\photos\protect.png'
& $taskPython $taskScript --project 'D:\photos\session01' plan --file 'D:\photos\plan.json' --id p01
# 展示方案，得到实际用户同意后登记；占位文字不是授权
& $taskPython $taskScript --project 'D:\photos\session01' approve --id p01 --scope overall --note '用户实际整体审批原话'
# 高风险 overlay 另逐项 approve --id p01 --scope 操作ID --note '该项实际审批原话'
& $taskPython $taskScript --project 'D:\photos\session01' run --id p01
# 全尺寸复核，用户明确人工通过后
& $taskPython $taskScript --project 'D:\photos\session01' review --version v0001 --decision pass --note '用户实际清晰度与融合验收原话'
& $taskPython $taskScript --project 'D:\photos\session01' export --version v0001 --output 'D:\photos\final01.png'
```

命令中原话是说明用占位文本，助手不得直接照抄。run/acceptance 非零退出码表示失败；失败版不推进 head，不能导出。导出需要全新 PNG 路径，在项目目录外，不覆盖原件。

```powershell
# 建分支或回退，历史不删除
& $taskPython $taskScript --project 'D:\photos\session01' branch --version v0000 --name cool
& $taskPython $taskScript --project 'D:\photos\session01' checkout --version v0001
# 独立当前像素验收，不替代项目导出门禁
& $taskPython 'C:\path\to\scripts\acceptance.py' 'D:\photos\source.png' 'D:\photos\candidate.png' 'D:\photos\protect.png' --report 'D:\photos\new-report.json'
```

versions 内的 image.png 是工作版本，不能直接复制并称为验收成片。人工失败登记 review --decision fail 后建立新方案。

依赖安装可能需要网络授权，脚本不自行安装。已有同名技能时先比较备份，不自动删除。超大图内存不足时停止，不通过缩图处理解决。异常中断残留 .lock 时确认无运行进程再人工移除；.tmp 或未登记目录也人工检查，不覆盖原件。
