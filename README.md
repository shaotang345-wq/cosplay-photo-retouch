# Cosplay Photo Retouch

Windows / Codex 的单一 Cosplay 摄影修图 Skill。由七个入口合并，保留原尺寸蒙版调色、分层合成、候选抠图、缓存、局部迭代、验收与回退。

## 安装

下载仓库后，在仓库根目录运行（Python 3.10+）：

```powershell
py -3 -m pip install -r cosplay-photo-retouch/requirements.txt
py -3 cosplay-photo-retouch/scripts/install.py
```

安装到 `$CODEX_HOME/skills`，未设置则为 `~/.codex/skills`。安装器校验文件哈希，将已有主包与六个旧入口移到 `~/.codex/skill-backups`，失败恢复旧安装。不会删除修图工程或模型。刷新/重开 Codex 后调用 `$cosplay-photo-retouch`；其他宿主的发现机制需自行核实。

可选抠图环境见 `cosplay-photo-retouch/references/cutout.md`，不默认下载模型。

## 精简内容

取消六个独立角色入口及互相路由；移除七包安装器、历史九图索引和案例清单、独立性能跑分脚本。保留已测试的图像引擎与旧工程兼容，避免为减少文件破坏保护门禁。参考图不随仓库发布。

## 使用

“只减弱右侧特效，脸和左侧保持不变，直接导出。”

“清理背景，保留人物位置和配饰形状；加少量有层次的花瓣，不能遮脸，不加月亮。”

“按两张参考分别借鉴光照和粒子景深，只生成独立素材，不重生整张照片。”

先按 SKILL.md 制作原生尺寸保护蒙版与计划。代码不内置 AI 生成服务、Photoshop 或自动审美；面部/范围保护依赖正确蒙版，感知清晰度需实际视觉检查。仅导出通过门禁的成片。

## 测试

```powershell
py -3 -m unittest discover -s cosplay-photo-retouch/tests -v
```

来源和取舍见 `cosplay-photo-retouch/references/merged-sources.md`。第三方工具与模型不打包。
