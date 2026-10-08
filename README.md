# Origin科研绘图

<img src="plugins/origin-scientific-plotting/assets/logo.png" alt="Origin科研绘图蓝色图标" width="80" />

**在 Windows 本机通过自然语言控制 Origin/OriginPro，生成可编辑科研图。**

本项目将 Origin MCP 接口与中文绘图 Skill 打包为 Codex 本地插件，覆盖数据读取、原生绘图、样式调整、图片导出和 `.opju` 项目保存。当前版本为 **0.1.2**。完整插件与独立 Skill 均提供源文件，可按研究项目调整工作流程。

[安装指南](#安装完整插件) · [独立 Skill](#单独使用-skill) · [使用示例](#使用示例) · [验证与演示](#验证与演示) · [常见问题](#常见问题) · [下载插件包](packages/origin-scientific-plotting-0.1.2.zip)

## 功能范围

| 工作内容 | 当前源码提供的工具或操作 |
| --- | --- |
| 数据读取与整理 | CSV/文本、Excel 导入；工作表读取与写入；列属性、排序、转置和工作表导出 |
| 原生二维图形 | 散点、折线、折线加符号、柱形、条形、面积、直方图和箱线图；追加或移除曲线 |
| 图形细节 | 误差棒、坐标轴、字体、线条与符号、图例、注释、参考线、双 Y 轴与图层位置 |
| 矩阵与颜色映射 | 矩阵数据、矩阵绘图和颜色映射；附 Viridis、Cividis 等调色板资源 |
| 分析操作 | 曲线拟合、统计和数据变换；具体模型与方法由实际工具参数决定 |
| 保存与复用 | PNG/JPG/TIFF/BMP、PDF/EPS/EMF 导出；Origin 项目保存与加载；图形模板保存 |

接口定义见[工作表](plugins/origin-scientific-plotting/server/src/origin_pro_mcp/tools/worksheet.py)、[图形](plugins/origin-scientific-plotting/server/src/origin_pro_mcp/tools/graph.py)、[样式](plugins/origin-scientific-plotting/server/src/origin_pro_mcp/tools/style.py)和[分析源码](plugins/origin-scientific-plotting/server/src/origin_pro_mcp/tools/analysis.py)。上表描述源码接口范围；全部图型、导入格式、拟合模型和样式在不同 Origin 版本上的组合尚未逐项验证。

[中文 Skill](skills/origin-plotting/SKILL.md)要求绘图前核对来源、列映射和单位，导出后检查实际图像，并交付可编辑项目。误差含义、样本量、缺失值处理和拟合条件缺失时，需要补充信息，不能凭空生成结论。

## 选择安装方式

| 方式 | 适用情况 | 获得的内容 |
| --- | --- | --- |
| **完整插件，推荐** | 同时配置 Origin 工具与绘图流程 | MCP 启动配置、完整服务源码、内置 Skill、图标和验证脚本 |
| **独立 Skill** | 本机已有可用的 Origin MCP 接口 | 中文绘图规则与流程，复用现有接口 |

插件通过 Windows COM 接口控制本机 Origin，由 MCP 向 Codex 提供工具。`ORIGIN_PRO_MCP_VISIBLE=1`使 Origin 窗口可见；daemon 模式使用会话实例。已有项目应按路径加载副本，不能仅凭软件已打开就假定插件正在操作指定窗口。实现见[连接模块](plugins/origin-scientific-plotting/server/src/origin_pro_mcp/origin_connection.py)。

## 安装完整插件

### 安装前准备

| 组件 | 要求与验证状态 |
| --- | --- |
| 操作系统 | Windows；本插件调用 Windows COM |
| Origin | 已安装并授权 Origin/OriginPro；实际验证版本为 **OriginPro 2026** |
| Python | Windows Python；实际验证版本为 **3.10.4**。配置脚本接受 3.10 及以上，其他版本需另外验证 |
| Python 依赖 | 已验证 **MCP 1.29.1、pywin32 312、Pillow 12.3.0**；依赖文件已固定这些版本 |
| Codex 与 Git | 本机可运行 `codex`、`git`，Codex CLI 提供 `plugin marketplace`与 `plugin add`命令 |

插件包含服务源码和资源。Python 解释器、虚拟环境与 Origin 许可证由本机提供。依赖见[`server/requirements.txt`](plugins/origin-scientific-plotting/server/requirements.txt)，验证记录见[`examples/verification.json`](examples/verification.json)。

### 克隆并配置 Python

以下命令在 **PowerShell** 中执行，后续命令以仓库根目录为工作目录。

```powershell
git clone https://github.com/zychen427/origin-scientific-plotting.git
cd origin-scientific-plotting

py -3.10 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r .\plugins\origin-scientific-plotting\server\requirements.txt
& .\.venv\Scripts\python.exe .\scripts\configure_runtime.py --python .\.venv\Scripts\python.exe
```

`py -3.10`需要已安装 Python 3.10。使用其他解释器时，应调整创建环境的命令，再按后文验证兼容性。

已有依赖齐全的 Windows Python 时，可直接传入其路径：

```powershell
python .\scripts\configure_runtime.py --python 'D:\OriginPython\.venv\Scripts\python.exe'
```

以上 `D:\OriginPython\.venv\Scripts\python.exe`是示例路径，执行前替换为实际解释器。添加 `--check`可只检查解释器与依赖，不修改插件配置。

配置脚本检查平台、Python 版本、MCP 主要版本和必要依赖，然后更新插件 `mcp.json`，并将原配置备份至 `.local-config/`。详见[`configure_runtime.py`](scripts/configure_runtime.py)。

### 注册并安装插件

先配置本地检出目录，再从仓库根目录运行：

```powershell
codex plugin marketplace add .
codex plugin add origin-scientific-plotting@origin-research-local
codex plugin list --marketplace origin-research-local --json
```

检查该插件是否已安装、已启用。随后新建 Codex 聊天，确认插件与工具加载；如果仍未出现，重启 Codex 后重新检查。

市场名称为 **`origin-research-local`**，插件标识为 **`origin-scientific-plotting@origin-research-local`**。同名市场已指向另一份副本时，先运行 `codex plugin marketplace list --json`核对来源，再按本机 CLI 支持的流程调整。配置修改后，可再次运行 `codex plugin add`同步安装副本。详细步骤见[安装与迁移文档](docs/INSTALL.md)。

### 验证 Origin 连接

```powershell
& .\.venv\Scripts\python.exe .\plugins\origin-scientific-plotting\scripts\verify_plugin.py --output .\verification
```

该命令检查插件文件、来源哈希、MCP 握手、工具发现和 Origin 只读状态。查看 `verification/verification.json`中的最终状态。使用已有环境时，将命令开头替换为配置时选择的 Python 路径。

完整绘图测试使用：

```powershell
& .\.venv\Scripts\python.exe .\plugins\origin-scientific-plotting\scripts\verify_plugin.py --plot --output .\verification
```

`--plot`使用明确标注的合成数据，在插件会话中创建双曲线、导出 PNG 并保存新的 `.opju`，文件名带随机后缀。该测试会创建 Origin 对象和输出文件，结果以实际文件和[验证脚本](plugins/origin-scientific-plotting/scripts/verify_plugin.py)报告为准。

## 单独使用 Skill

将整个[`skills/origin-plotting/`](skills/origin-plotting/)目录复制到本机实际启用的 Codex Skill 目录，保留以下结构：

```text
origin-plotting/
├── SKILL.md
└── agents/
    └── openai.yaml
```

在新的聊天中检查 Skill 是否被发现。独立 Skill 需要配合可用的 Origin MCP 服务；完整插件已经包含内置 Skill，无需重复复制。

## 使用示例

请求中给出文件路径、目标工作表、X/Y 列、单位、分组、误差列含义和输出目录，有助于减少反复确认。下面的路径均为示例，应替换为实际文件。

**CSV 双曲线**

> 读取 `D:\data\kinetics.csv`。A 列为时间，B/C 列为两组浓度。先核对表头和单位，再在 Origin 中绘制双曲线，使用不同符号，导出 PNG，并在新的输出目录保存可编辑 opju 项目。

**Excel 与误差棒**

> 读取 `D:\data\response.xlsx`的指定工作表。A 列为浓度，B 列为均值，C 列为已计算的标准差 SD。绘制带误差棒的散点图，核对误差列与均值列是否对应，保存原生项目。

**修改已有项目**

> 打开 `D:\data\analysis.opju`的副本，列出工作表和图形。将指定图的图例移到不遮挡数据的位置，调整字体与线宽，导出预览后检查实际渲染，另存为新项目。

**模型拟合**

> 对指定工作表的 X/Y 列进行拟合，先列出可用模型，再按明确选择的模型和拟合范围执行。输出参数与实际返回的诊断指标，并说明拟合假设和适用范围。

**批量导出**

> 列出当前插件会话中的图形，将需要交付的图导出到指定目录，检查是否存在同名文件，并保存新的 Origin 项目。

## 验证与演示

2026-10-08从实际安装目录运行插件，完成以下验证：

| 项目 | 实际结果 |
| --- | --- |
| MCP 握手与工具发现 | 通过；发现 **45 个工具** |
| Origin 原生绘图 | 创建含两条曲线的图形与数据工作表 |
| PNG 导出 | **1600 × 1134** 像素 |
| 可编辑项目保存 | 生成 `.opju`文件 |
| 文件记录 | 保存输出大小及 SHA-256 |

以上结果来自[验证记录](examples/verification.json)。公开记录将本机安装与输出路径替换为占位符；演示图和 Origin 项目保留原始字节，处理说明见[来源文档](docs/PROVENANCE.md)。

![Origin原生双曲线演示，数据为合成数据](examples/origin-plugin-demo.png)

[查看演示 PNG](examples/origin-plugin-demo.png) · [下载可编辑 Origin 项目](examples/origin-plugin-demo.opju) · [查看工具调用与验证记录](examples/verification.json)

演示数据用于验证插件。特定期刊的尺寸、字体、色彩和排版要求需要另外检查。API 返回成功后，仍应逐项检查导出图中的标题、单位、刻度、图例、误差棒和裁切情况。

## 仓库结构

```text
origin-scientific-plotting/
├── README.md
├── LICENSE
├── SHA256SUMS.json
├── .agents/plugins/marketplace.json
├── skills/origin-plotting/                 # 可单独安装的中文Skill
├── plugins/origin-scientific-plotting/
│   ├── plugin.json                        # 插件清单
│   ├── .codex-plugin/plugin.json           # 宿主兼容清单
│   ├── mcp.json                           # 本机启动配置
│   ├── assets/                            # 蓝色图标
│   ├── skills/                            # 插件内置Skill
│   ├── scripts/verify_plugin.py            # 本机验证脚本
│   └── server/                            # 启动器、源码、调色板、许可和来源记录
├── packages/                              # 完整插件ZIP
├── examples/                              # 演示PNG、opju和验证记录
├── scripts/                               # 配置、打包和校验脚本
└── docs/                                  # 安装与来源文档
```

## 重新打包与文件校验

```powershell
python .\scripts\package_plugin.py
python .\scripts\verify_distribution.py
```

打包脚本同步独立 Skill 与内置 Skill，生成包含隐藏兼容清单的单目录 ZIP，并更新 `SHA256SUMS.json`。校验脚本检查文件哈希、两份 Skill 的一致性、上游源文件哈希与 ZIP 内容。

配置脚本会更改 `mcp.json`中的 Python 路径，因此配置后分发清单可能与原始包不同；重新打包后再校验当前副本。已提交的[插件包](packages/origin-scientific-plotting-0.1.2.zip)保留本次验证机器的配置，另一台电脑应先配置自己的解释器路径再使用。

## 常见问题

| 情况 | 检查与处理 |
| --- | --- |
| 找不到 `py`或 `codex` | 检查程序是否安装并可从 PowerShell 调用；也可使用实际 Python 可执行文件路径 |
| Python 路径不存在或迁移后无法启动 | 重新运行配置脚本，传入本机依赖齐全的解释器，再同步安装副本 |
| `mcp.server.fastmcp`无法导入 | 用选定解释器重新安装固定的 `requirements.txt`；当前源码使用 MCP 1.x |
| 已安装插件，但聊天中没有工具 | 核对已启用、市场来源正确；新建聊天后检查，必要时重启 Codex |
| 同名市场已存在 | 用 `codex plugin marketplace list --json`核对根目录，按本机 CLI 支持的流程调整 |
| Origin 连接超时或后台进程未启动 | 保留实际错误；检查 Origin 授权、Python/pywin32 环境以及宿主启动 Windows 应用的权限 |
| 无法确认正在操作哪个项目 | 用 `list_worksheets`查看插件会话；按明确路径加载目标副本并回查对象 |
| 工具返回成功，样式看起来没变化 | 导出并检查实际图像，再回查目标图层与对象 |
| JSON 后出现 `[origin-mcp] Note` | 读取首个 JSON 对象并保留会话提示；验证脚本已兼容该格式 |
| 修改配置后哈希不一致 | 重新打包并校验当前副本；保留来源记录，区分预期修改与异常变化 |

仓库[换行规则](.gitattributes)保留检出文件的原始字节，避免 Windows 自动换行转换改变分发哈希。浏览器或手机本身无法启动本插件的 Windows stdio 进程。其他 Python/Origin 版本、全部导出格式和复杂图型仍需在目标环境中验证。

## 来源与许可

本仓库自有内容采用[MIT 许可证](LICENSE)。Origin 控制实现来自[youngminsw/Origin-Pro-MCP](https://github.com/youngminsw/Origin-Pro-MCP)，保留其[原始 MIT 声明](plugins/origin-scientific-plotting/server/LICENSE)。来源提交为[`1e9741a`](https://github.com/youngminsw/Origin-Pro-MCP/tree/1e9741af96c45bcac9e619c3ba32264bac6950e7)。

30 个上游源文件与资源的实际 SHA-256 位于[`server/PROVENANCE.json`](plugins/origin-scientific-plotting/server/PROVENANCE.json)。本机依赖元数据的调整和验证边界见[来源说明](docs/PROVENANCE.md)。

如需反馈问题，可提交[GitHub Issue](https://github.com/zychen427/origin-scientific-plotting/issues)，说明 Windows、Origin、Python 和插件版本、操作步骤及实际错误；附图或验证记录前，应去除无关的实验信息和个人路径。
