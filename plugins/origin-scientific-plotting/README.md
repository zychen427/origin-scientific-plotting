# Origin科研绘图

Windows本机Codex插件，蓝色图标。通过Origin COM接口操作原生数据和图形，提供中文绘图流程。版本0.1.2。

## 本机依赖

- 已安装并授权的Origin/OriginPro。
- 当前配置使用`G:\Codex\projects\Origin-Pro-MCP\.venv\Scripts\python.exe`，Python 3.10.4；MCP 1.29.1、pywin32 312、Pillow 12.3.0。
- 包内带有Origin-Pro-MCP源代码、MIT许可和SHA-256清单；不包含Python解释器、虚拟环境或Origin许可证。
- `mcp.json`的`command`绑定当前机器。迁移到另一台Windows电脑时，创建Python 3.10或更新的环境、安装`server/requirements.txt`，再将`command`改为新环境的Python绝对路径。
- `${PLUGIN_ROOT}`由插件宿主在启动时展开。服务器以stdio提供工具，不公开网络服务。

## 能力

工作表读取与导入、折线/散点/柱形等原生图形、追加数据系列、坐标轴和图例调整、误差棒、拟合与部分统计工具、图形导出及Origin项目保存。具体工具与参数以`list_tools`结果为准。每种图型与Origin版本的组合并未全部验证。

## 使用示例

“在Origin中读取指定CSV，A列作为时间，B/C列作为浓度，绘制两条曲线，轴上标明实际单位，导出PNG并保存新的opju项目。”

“读取已有Origin项目的副本，检查工作表和曲线后，将图例移到不遮挡数据的位置。”

## 本机安装

本次交付目录的上级包含`.agents/plugins/marketplace.json`，可使用已验证的本机CLI安装：

```powershell
codex plugin marketplace add 'G:\Codex\projects\origin_plugin_build_20261008'
codex plugin add origin-scientific-plotting@origin-research-local
```

安装完成后，在新的Codex聊天检查插件与工具是否已加载。账号中保存插件包不代表Windows stdio服务能在浏览器或手机中执行。

## 验证

```powershell
& 'G:\Codex\projects\Origin-Pro-MCP\.venv\Scripts\python.exe' .\scripts\verify_plugin.py --output ..\verification
& 'G:\Codex\projects\Origin-Pro-MCP\.venv\Scripts\python.exe' .\scripts\verify_plugin.py --plot --output ..\verification
```

默认只做握手、工具发现和只读检查。`--plot`在插件会话中用标注的演示数据创建双曲线图并保存新文件；不会清空当前会话或覆盖现有文件。

验证结果保存在交付目录的`verification`文件夹，最终状态以`verification.json`为准。

## 来源与许可

- Origin-Pro-MCP：https://github.com/youngminsw/Origin-Pro-MCP
- 来源提交：https://github.com/youngminsw/Origin-Pro-MCP/tree/1e9741af96c45bcac9e619c3ba32264bac6950e7
- 包内源代码的实际SHA-256：`server/PROVENANCE.json`。来源项目MIT许可见`server/LICENSE`。
- 插件格式：https://agent-plugins.org/schemas/1.0.0/plugin.schema.json
