# Origin 科研绘图插件

Windows 本机 Origin/OriginPro MCP 与中文绘图 Skill，版本 0.5.1。需要已安装并授权的 Origin 和 Windows Python 3.10 及以上，依赖见 `server/requirements.txt`。

完整安装步骤见 [GitHub 安装指南](https://github.com/zychen427/origin-scientific-plotting/blob/main/docs/INSTALL.md)。配置本机解释器后，宿主使用 `${PLUGIN_ROOT}` 展开插件目录并启动 stdio 服务。每个会话使用独立 Python worker 和 Origin 实例，默认通过 OriginLab 的 `originpro` 接口操作。

## 使用和验证

支持工作表导入与读写、原生图形、样式、误差棒、部分分析、导出和可编辑项目保存。已有项目按路径在隔离会话中加载副本。绘图、核验和保存完成后调用 `release_origin_session` 正常关闭会话创建的 Origin 实例。未保存或进程身份无法确认时会拦截释放。

```powershell
python .\scripts\verify_plugin.py --static-only --output .\verification
python .\scripts\verify_plugin.py --originpro --plot --output .\verification
```

静态验证检查清单、图标和源码哈希。`--plot` 启动独立 Origin 实例，使用合成数据创建图形并保存新文件。实机覆盖范围见 [0.5.1 验证记录](UPGRADE-STATUS.md)。

默认不自动覆盖保存项目、不自动关闭对话框；超时或连接异常不会主动关闭 Origin。新建或加载项目需显式 `replace_current=True`；导出拒绝覆盖同名文件。修改图例涉及源列长名称时需明确授权。

源代码基于 [Origin-Pro-MCP](https://github.com/youngminsw/Origin-Pro-MCP)，包含本地维护的修改。上游 MIT 许可见 `server/LICENSE`，分发源码哈希见 `server/PROVENANCE.json`。
