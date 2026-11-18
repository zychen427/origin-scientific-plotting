# 常用科研图绘制流程

## 验证基线
- 已验证：Origin 2020（上游历史验证；具体工作流见本 skill 内文）；Origin 2026 / Origin64.exe 10.3.0.180：工作表读写、line+symbol 图、出版样式、PNG 导出（2026-11-10）
- 未验证：其他 Origin 版本；复杂误差棒、全部图形类型、质谱/分组/批量工作流（详见 UPGRADE-STATUS.md）

## When To Use
为不同数据结构选择和创建 Origin 原生折线、散点、箱线、直方图、热图、等高线及双 Y 轴图。

## 共通步骤
优先使用 MCP，先 list_skills/get_skill("plot-preflight")，整理完整步骤并检查数据格式与目标图型是否匹配，再再确认会话与项目身份、读取表格并核对列映射、单位、缺失值与误差含义。用户要求现有窗口时不得自动启动另一实例；无法核对时说明限制。通常先绘制一张，核验再复用模板或批量。默认字体 Times New Roman；新图完成后调用 set_graph_font(graph_name, font_name="Times New Roman", target="all")，标题对象另行设置。字体和刻度在导出图中检查；3D 及颜色标尺等对象可能需额外处理，不能假设 all 覆盖全部对象。用户明确指定其他字体时优先遵从。

质谱折线图必须先读取 mass-spectrum，检查筛选峰表，并按用户的 0.1 m/z 网格补零要求处理适合的数据。

## 折线、点线和散点
连续有序 X 用 line 或 line+symbol；独立观测及相关性用 scatter。create_graph 指定实际的 X、Y 和可选 y_error_col；add_plot_to_graph 可增加系列及各自误差。不要自动连结无顺序的样本；不得推断误差类型。每条系列核验颜色、符号、图例及量程。

## 柱图与分组柱图
单列柱图可用 create_graph(plot_type="column")，通常以零为基线；负值及特殊情况按数据决定。两处理分组柱图参见 grouped-column。当前普通 create_graph/add_plot 接口没有行范围参数，不保证多系列柱子并排；需要先验证模板或范围映射。不要使用只支持折线/散点重绘的 ungroup_plots 改造柱图。

## 箱线与直方图
对原始观测用 create_graph(plot_type="box" 或 "histogram")，接口只使用单 Y 列；不能把均值及误差当作原始分布。箱线图需按 Origin 配置说明箱须和异常值规则；直方图核对分箱宽度和频数/密度定义。多组箱线图的分组支持应先在测试图核验，不能假设单 Y 接口自动处理多组。

## 热图、等高线与曲面
规则网格用 create_matrix 和 set_matrix_data；散点 XYZ 可使用 worksheet_to_matrix 网格化，记录插值方法及参数并检查缺失。create_matrix_plot 可创建 heatmap、contour、surface；用 colormap 设置色带与实际数据范围并保留颜色标尺。对于连续色感可用 heatmap 的 levels 参数；不要把插值结果描述成原始观测。X/Y/Z 轴和色标单位需核对，3D 文本单独检查字体。

## 双 Y 轴
用 create_graph 建立第一组，add_second_y_axis 加入第二组，再分别标注轴和单位，核对量程和系列映射。不得让视觉比例暗示不存在的相关性；用清晰图例或轴颜色区分。

## 保存与验证
检查图是否有正确数据、单位、轴范围、误差棒、文字与图例，导出预览并保留可编辑项目。apply_publication_style 会修改颜色和其他外观；设置 legend_entries 当前会修改源列长名称，应先告知并确认是否适用，保留原始表的语义。该工具仅在用户指定时设置轴范围，默认保留原范围。图层内与图外图例位置支持有限；图下方布局应单独验证。
