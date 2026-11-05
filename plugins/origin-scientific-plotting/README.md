# Origin 科研绘图插件

Windows 本机 Origin/OriginPro MCP 与中文绘图 Skill，版本 0.2.1。需要已安装并授权的 Origin 和 Windows Python 3.10 及以上；安装固定依赖见 `server/requirements.txt`。本包不包含 Python 或 Origin 许可证。

配置本机解释器后，宿主使用 `${PLUGIN_ROOT}` 展开插件目录并启动 stdio 服务。完整安装步骤见仓库根目录的 `README.md` 与 `docs/INSTALL.md`。daemon 默认使用独立的每用户锁文件，避免意外连接旧版服务。

## 使用和验证

支持工作表导入与读写、原生图形、样式、误差棒、部分分析、导出和可编辑项目保存。具体工具与参数以实际服务为准；已有项目应先确认连接的 Origin 会话并保留副本。按 `skills/origin-plotting/SKILL.md` 在绘图前检查数据与需求，导出后检查图形和项目。

```powershell
python .\scripts\verify_plugin.py --output .\verification
python .\scripts\verify_plugin.py --plot --output .\verification
```

默认验证握手、工具发现和只读状态。`--plot` 使用合成数据创建图形并保存新文件。目标机器上的测试结果取决于 Origin 版本、许可、桌面权限和依赖。

默认不自动覆盖保存项目、不自动关闭对话框；超时或连接异常不会主动关闭 Origin。新建或加载项目需显式 `replace_current=True`；导出拒绝覆盖同名文件。修改图例涉及源列长名称时需明确授权。

源代码基于 [Origin-Pro-MCP](https://github.com/youngminsw/Origin-Pro-MCP)，包含本地维护的修改。上游 MIT 许可见 `server/LICENSE`，分发源码哈希见 `server/PROVENANCE.json`。
