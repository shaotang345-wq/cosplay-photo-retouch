# V3 运行协议

当前为 V3.2；下列新增命令与约束优先于旧描述。旧工程、CLI、素材与版本不删除，字段按需兼容，不能批量迁移私人图片。

## 常规短路径

同轮只读一次当前命令、保护/审批/预算/导出约束与用户偏好；已读且未变的内容复用。默认只走 context → route/revise 或 plan → 必要审批 → run → preview/inspect → export，NO_ACTION_REQUIRED 不做像素操作。简单修改不启动 Analyzer、不加 finish 调色；强制最终 QC/视觉验收照常执行。参考分析、生成、反馈/风格、系列、分支合并和备用修补只在本轮需求触及时读对应段落与资料；不默认收集全部字段。缺失字段仍按实际命令契约补齐，不能省略保护蒙版、实际授权、必需范围和五项视觉记录。

## 兼容与共享状态
旧 retouch.py/acceptance.py 及项目不删除。先用旧 init 创建原图、Pixel Freeze 保护蒙版项目，再 v3 attach 提交完整 subject 蒙版；或对旧工程当前合格 head attach。attach 不改旧 head，把基准副本、v3 状态写入同一个 project.json 的 v3 字段。旧展平的火焰无法恢复图层；只有新登记配方支持差量修改。attach 后不要交替用旧 CLI 改 head，检测变化将拒绝继续，另建项目重新迁移。

已有 assets 内容寻址目录兼任 source/masks/layers，避免重复复制；state/v3/plans 保存绑定方案与授权；state/v3/versions 保存配方、PNG、QC；state/v3/cache 保存原生 .npy 前缀缓存。analysis/references 为分析材料，previews 为展示文件，qc 为失败记录。状态包含 subject bbox、模式、分支、图层版本、reference_map、反馈、偏好和实测 telemetry。原始数据始终保留。

Geometry Lock：后端没有移动/旋转/缩放/warp；subject 上只允许不改坐标的 tone，background 模块不可接触 subject，生成 overlay 默认不可覆盖 subject；已登记的前景 VFX 例外见本文 V3.1 规则。因此不会通过贴一张重绘人物绕开变换禁令。Pixel Freeze：项目 protected 与原图逐像素比较；本轮 scope.freeze 与本轮父版本比较。subject/freeze/allowed 均为同尺寸 L PNG，非零为选区，必须人工确认语义覆盖；0%权限必须落到 allowed 排除与 freeze 锁定，百分数本身不提供保护。

## 命令
统一：`python scripts/v3.py --project PROJECT ACTION --file REQUEST.json`，JSON 路径使用绝对路径。所有 CLI 写操作带项目锁。Python API 供测试或单进程集成，外部并发调用必须加 retouch.locked。

- attach：`{"subject":"C:/photos/subject.png"}`。
- metadata：不需要 file；缓存尺寸/模式/方向，不假称自动理解光照。
- plan：下面的完整原生图层配方。每次从 attach 基准重构，绝不能把旧火焰展平再叠一遍。
- revise：与 plan 相同的 do/do_not/scope 等，但以 `"updates":{"fire-right":{"opacity":0.2}}` 代替 layers。只改已有层；未知层拒绝。
- approve：`{"pid":"p1","scope":"overall","quote":"实际用户原话"}`；高风险层 scope 为 op.id；整轮 risk=high 还需 high-risk，低置信度高风险还需 uncertain。可以登记同一条真实回复包含的多项授权，身份不由脚本认证。
- run：`{"pid":"p1"}`，先审批再执行。QC_FAIL 留错误、不推进 head；无差异返回 NO_ACTION_REQUIRED。
- attempt：`{"pid":"p1","region":"right","kind":"generation"}` 或 correction。先登记再使用宿主工具；失败也消耗预算，不循环调用。登记返回票据但不执行模型；外部调用后用 attempt-result 登记成功/失败、实际工具与秒数；票据数不是已成功生成数。
- preview：`{"vid":"v0001","rois":[[0,0,320,320]]}`。整体可缩小；ROI 原生裁片只作检查，不改变成片。
- inspect：`{"vid":"v0001","checks":{"space":{"decision":"pass","observation":"实际观察"},"edges":...,"lighting":...,"effects":...,"intent":...},"evidence":["C:/.../overview.png","C:/.../roi-0.png"]}`。五项必须实际看图后逐项填写；不是自动审美评分。
- export：`{"vid":"v0001","output":"C:/photos/new-final.png","quote":"实际已有导出授权"}`。目标须新建、项目外 PNG。重新核对原图/资产/版本、配方输出、范围、冻结区、启发式 QC、视觉证据；无 skip 参数。
- checkout：`{"vid":"v0001","branch":"alternate"}`；branch 可省略，回退不删除历史。选取另一分支的某个图层时读取其 recipe，将所选层写入新 plan；保留当前其他层，重新审批及验收。这是显式选层合并，不是自动冲突解决。
- state：查看共享状态。

## 最小方案
```json
{
 "id":"p1", "do":["背景降饱和"], "do_not":["改脸","改人物位置","改发丝"],
 "mode":"standard",
 "scope":{"allowed":"C:/photos/bg.png","freeze":"C:/photos/subject.png","geometry_lock":true},
 "layers":[{"module":"background","op":{"id":"bg-grade","type":"tone","mask":"C:/photos/bg.png","saturation":0.98}}],
 "reference_map":[], "effect_budget":{"primary":1,"secondary":2}, "risk":"low", "confidence":0.9
}
```
方案 risk 仅允许 low/high；confidence 为 0 到 1 的有限数值，不能用布尔或字符串。effect_budget 仅含 primary/secondary，分别是 0 到 1、0 到 2 的整数。图层 ID 不得使用审批保留名 overall、uncertain、high-risk；旧配方若用了后两者，需要改名并重新登记真实授权，不能静默迁移。

module 为 retouch/background/vfx/finish；op 为旧 contracts.md 的 tone 或 overlay。颜色参数非物理色温，不可声称 gains 精确等于 -300K。只调用实际所需模块。reference_map 每项 reference/role/weight/priority/do_not_copy/group；reference_groups 将相同 role/group 合为一组，effective_weight 取最大值而非累加；Master 仍需解释冲突与采纳理由，权重不自动影响像素。登记过的参考 id 自动绑定实际资产哈希，旧符号参考保留兼容但不能声称文件已验证。组合冲突按用户硬约束、当前明确指令、维度优先级处理，不能复制参考构图改变主体几何。

## 缓存与失效
cache-get / cache-put：`{"name":"face-analysis","level":1,"deps":["face"],"inputs":{"mask_sha256":"实际哈希"},"value":{"observations":[]}}`；get 不含 value，命中返回分析，缺失明确 CACHE MISS。昂贵分析必须先 get，再分析，最后 put，不能先算完才检查缓存。元数据命令自动执行此逻辑。

L1：original、subject、face、hair、costume、props、original_lighting、composition。L2：background→environment_light/depth/vfx→interaction→finish。background 更新不会失效 face/original_lighting。L3：reference 输入哈希+分析规范版本，deps=[]，保存色彩主次强调色、光向软硬、主体环境关系、前中后景景深、材质、特效、可复用规则、不可迁移元素、风险、观察/推断/置信度。L4：独立素材留在哈希 assets；调整 mask/opacity 不重新生成。配方前缀缓存按基准+整段上游图层参数/资产哈希+保护策略命中，上游变化下游自然换 key。采用最长前缀恢复；小面积有效范围保存原生数组块，大范围保存完整检查点。所有源/素材仍逐次校验 SHA-256，缓存内容也校验；不是跳过门禁。

旧 cache-get/put 的 inputs 哈希仍由调用者提供；推荐提供 files 映射，每次访问自动重新计算文件哈希。reference-analysis 自动捕获实际图像和分析规范版本，不将历史记录当作参考照片实时可用性的证明。不得复用跨项目语义资产而不核对角色、场景、尺度、光照和用途。缓存文件有内容校验，但项目不是防恶意篡改的安全数据库。缓存原生数组占磁盘；不含模型/GPU缓存，不承诺低峰值内存。只清理可重算的缓存，不删素材和版本。

## 模式及停止
fast：1整体预览、0自动ROI、0生成、0自动修正；standard 默认：1整体+最多2个原生ROI、2生成票据、1修正、同区域最多2票据；detail：1整体+最多4ROI，相同生成/修正预算，人工更细复核。所有模式硬门禁完全一致；standard/detail 的实质成本差异主要是自动 ROI 数量，语义检查粒度由助手执行，未自动化。不能承诺 detail 自动得到更好审美。

run 失败后计划终止，新计划仅针对失败模块。Master 不得通过反复新建计划绕过原任务的生成预算；票据按共享 task 计数，新建修正计划不会重置预算。只有收到独立新任务时，使用 task 命令提交新 id 和真实 quote 才能开启新预算；禁止将失败重试伪装成新任务。脚本无法认证用户身份。低置信度高风险审批标志可强制，置信度真实判断和最低成本路线仍由助手负责。

## 反馈和偏好
feedback：version、decision(GOOD/BAD)、category(Intent/Planning/Execution/QC/Performance)、quote、reason、module。只能记录用户明确认可/否决，不能把助手自检当用户喜欢。profile：level(persistent/project/image)、values、quote；合并 Image > Project > Persistent，但不自动应用滤镜。持久偏好当前只持久于项目；跨项目用户偏好库和自动审美学习未实现。系列只共享调色/世界观/照明语言/特效语言/输出规范，蒙版几何ROI必须按照片独立。

## 能力边界
可执行：原生蒙版调色、原生图层合成、可编辑配方、差量参数/蒙版修改、缓存与依赖失效、门禁、预算登记、版本和预览。依赖助手：语义意图、参考深度分析、材质判断、画面融合、美观、涂抹感、GOOD/BAD应用。外部接口而非实现：ROI生成、背景重建、独立素材写实化；宿主工具不可用时如实停止。未实现：自动审美评分/修复、Photoshop/PSD/RAW/16-bit、物理重照明、自动HSL/曲线/降噪、跨进程GPU调度。边缘能量阈值仍可能误拒绝正常降对比，不能冒称感知清晰度保证。

## 前景特效与面部硬保护（V3.1）
用户允许在美观、符合空间遮挡时让独立特效位于人物上层，例如少量花瓣经过衣袖或裙摆。绝不能出现在脸部，包括眼睛、眉毛、鼻、口、面部皮肤及安全余量；特效核心、粒子、辉光和雾都受此限制。面部保持原始像素，不重绘。前景遮挡不等于授权重绘人物、改配饰形状或覆盖关键服装图案。优先低覆盖率、疏密变化，实际查看整体与原生局部后才导出。

执行时必须登记完整 face 蒙版、局部 foreground 许可蒙版与真实授权；face 必须包含于项目 Pixel Freeze 且不与 foreground 相交。禁止为了放特效直接取消全部人物保护。v3.py attach 支持 face、foreground、foreground_quote；仅 vfx 模块可在指定人物局部叠加透明素材，单层可见覆盖不得超过 subject 的15%，累计覆盖与美观仍须视觉检查。背景模块不因此取得修改人物的权限。原始人物层不变，前景合成区像素会变化，不能宣称该区逐像素不变。旧项目未配置此权限仍禁止主体 overlay。

## V3.2 最小计划与新接口

1. context（无 file）读取配方、参考、GOOD/BAD、缓存依赖、任务预算、三级偏好；Image > Project > Persistent。只有本轮相关缓存缺失才调用 Analyzer。
2. route 接受结构化的已有层修改，返回最少的 request 与 run_modules/reuse_layers；并不自动理解自然语言。示例：
```json
{"id":"less-fire","do":["右侧火焰减弱"],"do_not":["修改脸","改变左侧"],"updates":{"fire":{"mask":"C:/photos/right-weaker.png"}},"scope":{"allowed":"C:/photos/right.png","freeze":"C:/photos/left-and-face.png","geometry_lock":true}}
```
把用户要求映射为已有层 ID 与实际蒙版，不能把“右侧”直接替换成全层 opacity。route 的 NO_ACTION_REQUIRED 不创建计划或版本；若要输出已有成片，仍须现有 export 门禁。PLAN_REQUIRED 的 request 交给 revise；它保留未变图层与参考映射。完整配方仍可 plan；图层顺序参与差量与缓存失效。
3. 纯参数/蒙版 revise 自动设 generation_policy=none，attempt 拒绝生成；替换已有 layer 文件可走资产路线，但不意味着必须调用模型。只有已批准的真实新增资产需求才允许 assets 路线。

scope 可增加 modules：`{"background":"C:/photos/background-permission.png","vfx":"C:/photos/right-permission.png"}`。模块蒙版为原尺寸 L PNG、非零允许；约束本轮改变或移除的对应模块层的影响差量：只改 mask 时比较权重变化；同混合方式的 overlay 比较权重/颜色变化；参数、类型或顺序变化保守检查完整有效范围。全局 allowed/freeze 仍对父版本→成片的实际差异生效，两种限制共同检查。DO/DO NOT 必须非空字符串数组；targets 可用 0–1 数值表达内部审美目标，不是精确审美测量。

### 参考与分析缓存
reference-analysis：`{"id":"color-ref","path":"C:/photos/ref.png","schema":"photographic-v1"}`。先读，缺失报 CACHE MISS；实际看图后添加 value 对象登记摄影分析，结果按实际文件内容哈希+schema 缓存。相同内容可换 id 复用；换图或 schema 必须更新。程序检查文件，不自动产生视觉结论。value 可包含 Style Class、主次/强调色、光向/软硬、主体环境关系、前中后景/景深、材质、特效、可复用规则、不迁移元素和风险；unknown 如实记录。

cache-get/put 可提供 `"files":{"reference":"C:/photos/ref.png","mask":"C:/photos/mask.png"}`，文件内容变化自动缓存 miss。L1 原始人物/原始光照保留；background 更新使环境/景深/互动/finish 失效；retouch 更新 grading→finish，不无意义失效原始人脸观察。变更当前外观的分析应依赖 grading 或 interaction，而非伪装成永久原始分析。

### 外部调用账本
attempt 可指定 uses_generation：generation 必须 true；correction 默认为 true，只有纯传统修正设 false。standard/detail 每个共享 task 最多 **2 次总生成尝试**，其中生成式 correction 也计入这2次；最多1次自动 correction，同区最多2票据。fast 不允许生成或自动 correction。失败不退款；新建计划、分支和 checkout 均不重置预算。task ID 永不复用，只有实际独立新请求才 new_task。

attempt-result 示例：`{"pid":"p1","ticket":1,"status":"failure","seconds":12.4,"tool":"实际工具名","reason":"实际失败原因"}`。status 为 success/failure，seconds 是调用方真实计时，outputs 可列实际文件。每票只能完成一次；工具未调用或未回报结果保持 unknown，不能虚构秒数或成功。原生脚本不执行模型、不认证外部调用，也不能阻止宿主绕过账本。

### 质量、版本与耗时
完成必要审批才进入 PLAN_APPROVED；部分审批仍 PLAN_PENDING。run 为 EXECUTING→QC_RUNNING→QC_PASS/QC_FAIL/NO_ACTION_REQUIRED。QC_FAIL 终止该计划，不能 approve 重新打开；只新建针对失败模块的计划。PNG 写入或版本登记失败不推进 head，残留诊断目录保留，下一版选新的 ID。

每轮 telemetry 是当前 run 的计数差量：baseline 解码、render、qc、PNG 写入、总时间、实际模块计算时间、缓存 hit/miss、asset_decodes、缓存读写字节、生成票据/已报告调用/修正。模块没有重新计算时，不填假耗时。events 另记 plan、preview、inspect、export 的真实方法耗时，未包含宿主推理、进程冷启动和事件自身落盘。反馈 GOOD/BAD 另落 reference_feedback 文件，仍只根据真实明确用户反馈。

QC 只缓存绑定原图/保护哈希的原始边缘能量；每版仍计算成片能量、比较冻结区、alpha、尺寸与实际权限。export 重查完整五项视觉记录、证据哈希和模块范围；最终 PNG 与工作版本字节相同。任何模式无 skip 开关。视觉美感、蒙版语义覆盖、配饰形状仍需人实际查看。

本版本提供有界 64 MiB 解码 LRU，但完整画布、浮点计算和磁盘缓存仍占内存/空间；不是 GPU 或模型会话缓存。旧 engine=3 数组不删除，新缓存使用独立 engine=32 key。完整性异常先保留诊断，仅清理可重算缓存，不删除版本或素材。
