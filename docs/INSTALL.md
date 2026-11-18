# 安装和迁移

## 运行环境

需要 Windows、已授权的 Origin 或 OriginPro，以及 Windows Python 3.10 或更高版本。实机测试使用 OriginPro 2026、Python 3.10.4、originpro 1.1.15 和 OriginExt 1.2.6。测试范围见[0.5.1 验证记录](../plugins/origin-scientific-plotting/UPGRADE-STATUS.md)。

完整插件采用 stdio MCP 连接，由宿主展开 `${PLUGIN_ROOT}`。每个会话启动独立的 Origin 实例，默认后端为 `originpro`。`ORIGIN_PRO_MCP_VISIBLE=1` 使会话窗口可见。已有项目应按路径加载副本。绘图和保存完成后，`release_origin_session` 检查保存状态，再正常退出该实例。

## 克隆与配置

在本机克隆仓库并创建Python环境，安装`plugins/origin-scientific-plotting/server/requirements.txt`。运行：

```powershell
& .\.venv\Scripts\python.exe .\scripts\configure_runtime.py --python .\.venv\Scripts\python.exe
```

也可以传入已有、依赖齐全的 Windows Python 的绝对路径。脚本检查平台、解释器和依赖后，会把解释器和按版本区分的用户目录锁文件路径写入插件的 `mcp.json`。配置备份保存在 `.local-config/`。

## 安装插件

从仓库根目录运行：

```powershell
codex plugin marketplace add .
codex plugin add origin-scientific-plotting@origin-research-local
```

本地市场根目录必须是当前已配置的仓库检出目录。若同名本地市场此前指向另一份副本，先检查`codex plugin marketplace list --json`，确认使用目标目录后再按本机CLI支持的流程调整来源。不要直接编辑Codex插件缓存。

在新的聊天中检查插件加载和工具发现。插件安装、聊天加载、MCP启动和Origin绘图验证是不同步骤。安装记录不能证明旧聊天已经热加载。

## 验证

```powershell
& .\.venv\Scripts\python.exe .\plugins\origin-scientific-plotting\scripts\verify_plugin.py --static-only --output .\verification
& .\.venv\Scripts\python.exe .\plugins\origin-scientific-plotting\scripts\verify_plugin.py --originpro --plot --output .\verification
```

静态检查覆盖清单、图标和源码哈希。绘图测试会创建隔离实例，使用合成数据绘制双曲线、导出 PNG 并保存新项目。运行结果写入 `verification/verification.json`。

## 单独安装Skill

复制整个`skills/origin-plotting`目录到本机实际使用的Codex Skill目录，然后在新的聊天检查发现情况。独立Skill需配合可用的Origin MCP接口；仅复制Skill不会安装Origin或MCP依赖。

## 安装包

下载[完整插件 ZIP](../packages/origin-scientific-plotting-0.5.1.zip)并解压到 Windows 本地目录，保留隐藏的 `.codex-plugin` 清单。安装 `server/requirements.txt` 后，在解压目录的 `mcp.json` 中将 `command` 指向该 Python 的绝对路径，并在 `env` 中设置本机独立的 `ORIGIN_PRO_MCP_LOCKFILE`。将本地市场的 `source.path` 指向解压的插件目录，再按上文安装。直接克隆仓库可使用配置脚本完成路径设置。
