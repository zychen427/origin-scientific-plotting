# 安装和迁移

## 运行环境

需要Windows、已安装并授权的Origin/OriginPro以及能使用pywin32的Windows Python。验证环境为OriginPro 2026、Python 3.10.4、MCP 1.29.1、pywin32 312、Pillow 12.3.0。Python 3.10以外的解释器和其他Origin版本需自行运行验证脚本，不能据此声称已通过测试。

完整插件采用stdio MCP连接，由宿主展开`${PLUGIN_ROOT}`。`ORIGIN_PRO_MCP_VISIBLE=1`使Origin窗口可见；daemon模式为会话提供Origin实例，不能据此声称接管用户手动打开的任意窗口。已有项目应使用项目路径加载副本。

## 克隆与配置

在本机克隆仓库并创建Python环境，安装`plugins/origin-scientific-plotting/server/requirements.txt`。运行：

```powershell
& .\.venv\Scripts\python.exe .\scripts\configure_runtime.py --python .\.venv\Scripts\python.exe
```

也可以传入已有、依赖齐全的Windows Python的绝对路径。脚本会先检查平台、Python版本、MCP主要版本和所需依赖，再更新插件的`mcp.json`。修改前的配置保存在忽略上传的`.local-config/`目录。

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
& .\.venv\Scripts\python.exe .\plugins\origin-scientific-plotting\scripts\verify_plugin.py --output .\verification
& .\.venv\Scripts\python.exe .\plugins\origin-scientific-plotting\scripts\verify_plugin.py --plot --output .\verification
```

默认检查文件、来源哈希、MCP握手、工具发现和Origin只读状态。`--plot`使用标注的合成数据创建双曲线，导出PNG并保存新`.opju`，不清空会话或覆盖已有文件。运行结果写入输出目录的`verification.json`。Windows应用运行权限不足时，沙箱中的后台进程可能无法启动；该结果不能直接推断Origin安装损坏。

## 单独安装Skill

复制整个`skills/origin-plotting`目录到本机实际使用的Codex Skill目录，然后在新的聊天检查发现情况。独立Skill需配合可用的Origin MCP接口；仅复制Skill不会安装Origin或MCP依赖。

## 安装包

`packages/origin-scientific-plotting-0.1.2.zip`包含一个完整插件目录及隐藏兼容清单，保留此次本机验证配置。迁移到另一台机器前，应展开并配置其`mcp.json`，或使用仓库中的配置脚本配置检出目录后重新打包。解释器、虚拟环境与Origin许可证需要在本机自行提供。
