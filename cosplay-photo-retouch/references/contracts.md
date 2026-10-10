# 输入、项目与方案规范

## 支持范围
原图：8-bit RGB/RGBA PNG 或 JPEG，解码后像素作为基准。拒绝多帧、EXIF Orientation 不为 1、CMYK、灰度、调色板、16-bit、RAW。严格 sRGB 工作流：嵌入 ICC 的原图拒绝，须先在可信色彩管理工具中检查并另存明确 sRGB 8-bit 文件，另存行为不属于脚本的强保证。无 ICC 不等于已证明 sRGB，使用前人工确认。JPEG 原始压缩字节被保留，导出 PNG 与其解码像素比较，不宣称恢复 JPEG 丢失细节。输出不保留 EXIF/GPS，只使用无 ICC 的 sRGB 假设，拒绝特殊 PNG gamma/chromaticity 元数据。

保护蒙版：同尺寸 L 模式 PNG，非零全部锁定；必须非空，可以全白。灰阶不是保护强度。蒙版由用户确认覆盖整个人物、道具、边缘余量；程序无法判断漏标。

操作蒙版：同尺寸 L PNG，0 不修改，255 全强度，其余为混合权重。图层：同尺寸 RGBA PNG，透明像素无影响。素材必须在原网格直接制作。禁止把整图 AI 输出加透明边缘包装成局部素材。

## 方案 JSON
UTF-8；相对路径以 JSON 文件所在目录为基准。未知字段、未知操作、非有限数、越界参数拒绝。至少一项操作，每项 ID 唯一。

```json
{
  "summary": "背景稍冷，保留人物所有像素",
  "operations": [
    {
      "id": "bg-tone",
      "type": "tone",
      "mask": "background-mask.png",
      "exposure": -0.1,
      "contrast": 1.02,
      "saturation": 0.9,
      "gamma": 1.0,
      "gains": [0.98, 1.0, 1.03]
    },
    {
      "id": "spark",
      "type": "overlay",
      "mask": "spark-mask.png",
      "layer": "spark-rgba.png",
      "blend": "screen",
      "opacity": 0.25,
      "risk": "strong_effect"
    }
  ]
}
```

tone 参数可省略，默认恒等：exposure [-2,2] EV、contrast [0.5,1.5]、saturation [0,1.5]、gamma [0.5,2]、gains 三通道各 [0.5,1.5]。计算在 8-bit sRGB 编码值域，非物理光度模型。操作原 alpha 不变。

overlay 必填 mask/layer/risk；blend 为 normal/screen/multiply，opacity [0,1]。risk 为 cosmetic、background、repaint、strong_effect。后三者单独审批。程序不会凭图像判断用户是否误写 risk，助手必须按实际用途分类。

任何操作的有效蒙版与保护区重叠就拒绝（overlay 还考虑 alpha 和 opacity）。有意修改脸/衣服的请求无法在此后端兼顾严格像素锁，明确说明冲突而不是缩小保护蒙版。可以提出仅改背景的可执行方案。

## 项目
project.json：原图/保护蒙版哈希、尺寸、head、branch、分支映射。assets/：按 SHA-256 命名的原始字节。plans/：不可覆盖、绑定父版本的方案及审批。versions/：不可覆盖版本、image.png、report.json、review.json。每版保存 parent、branch、plan digest、输出哈希。路径限制在项目内部；ID 只接受字母数字和短横线/下划线。工程元数据不抗恶意篡改；源/资产/版本图像变化可检测，审批或人工复核的身份不可认证。

不得并行写同一项目。脚本使用排他锁阻止同时写入；异常退出可能留下 .lock，确认没有进程运行后人工移除。磁盘失败可能留下未登记版本目录，保留诊断后新建计划；不自动覆盖或删除。
