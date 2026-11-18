---
name: origin-plotting
description: 在Windows本机通过隔离的Origin会话导入数据、创建和修改可编辑科研图、导出文件并保存项目。
---

# Origin科研绘图

使用本插件的类型化 MCP 工具和 Origin 原生可编辑对象。每个会话使用自己的 Python worker、STA 队列及经 PID、进程映像、创建时间核验的 Origin；默认优先 originpro 对象 API，未迁移能力使用同一实例的 OriginExt/LabTalk。不要调用 `originpro.attach()`，不要用其他会话的对象或窗口，也不要把进程身份当作项目内容核验。

## 开始工作

- 调用 `list_skills`，绘图前读取 `plot-preflight`；论文图读取 `publication-figure`；按数据类型读取 `excel-to-origin`、`grouped-column`、`mass-spectrum` 或 `plot-recipes`。原始 LabTalk 前读取 `labtalk-gotchas`。
- 首次工作调用创建隔离实例；调用 `diagnose_origin_runtime` 核对 worker PID、Origin PID、映像、创建身份和 `window_identity_verified`。`list_open_origin_windows` 为只读检查；本版本不连接用户已经打开的窗口，`connect_existing_origin` 会明确拒绝。用户指定已有项目时，按授权加载副本，不声称操作了现有窗口。
- 用 `list_worksheets` 和实际工具返回值确认名称；新建或打开项目后重新查询工作表、图层和曲线，不能使用此前项目的引用。新建或加载项目需先保存所需内容，并明确传 `replace_current=True`。
- 缺少来源、列映射、单位、重复数或误差定义时先核对；不能推测原始数据、统计量或显著性。保留缺失值和来源，不自动插值或填零。

## 创建、核验与释放

1. 创建工作表并写入，或导入文件；回读数值、列名、单位和分组。保留原始文件；面向用户的数据列名与显示标签使用有意义的中文，内部短名遵守 Origin 约束。
2. 创建图形并检查图层、曲线和数据映射；有误差棒时验证其来源及 SD、SEM 或置信区间含义。根据研究问题选图型与拟合模型，核对拟合范围、参数和残差；本工具线性拟合验收不代表全部模型适用。
3. 默认白底、四边封框，英文和数字 Times New Roman、中文宋体，轴标题粗体；保留用户指定样式。按实际图形检查标签、图例、字体、刻度、颜色与裁切，不改变数据改善外观。
4. 导出预览并检查实际图像；按需求导出矢量格式，保存可编辑 OPJU。复杂图型、其他 Origin 版本、字体嵌入和未覆盖工具按未验证处理。
5. 保存后调用 `release_origin_session`。未保存或窗口及归属不可核验时拒绝关闭；成功会正常退出本会话创建的 Origin。失败或超时可能已部分修改：不要自动重放，先检查原会话、项目和窗口。worker 崩溃后原会话不能静默重建；保留 Origin，按诊断和 README 的恢复路径核验。

Origin 2026 / Origin64.exe 10.3.0.180 的合成验证范围见插件根目录 `UPGRADE-STATUS.md`。0.5.1 已检查两条带 Y 误差棒曲线的对象角色和重开；矩阵等高线中缺失单元格的视觉编码尚未验证，含缺失值时须单独核对并说明。来源：[OriginLab External Python](https://docs.originlab.com/externalpython/)；[ACS 作者指南](https://researcher-resources.acs.org/publish/author_guidelines)。
