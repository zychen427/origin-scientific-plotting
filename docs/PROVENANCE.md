# 来源、许可和验证边界

Origin COM控制实现来自：https://github.com/youngminsw/Origin-Pro-MCP 。

发布版在[上游提交 1e9741a](https://github.com/youngminsw/Origin-Pro-MCP/tree/1e9741af96c45bcac9e619c3ba32264bac6950e7)的基础上维护，包含会话隔离、绘图工作流与依赖调整。插件 `server/PROVENANCE.json` 记录当前发布的绘图服务源码和资源哈希。公开 0.5.1 分发版的绘图服务文件与已安装、实测的 0.5.1 逐字节一致，启动路径和测试配置可在本机设置。[0.5.1 验证记录](../plugins/origin-scientific-plotting/UPGRADE-STATUS.md)

上游作者`youngminsw`的MIT声明位于插件`server/LICENSE`。本仓库自有插件说明、中文Skill和维护脚本适用仓库根目录MIT许可证，保留`zychen427`的声明。打包后插件同时保留其上游许可文件。

源清单、完整插件包、独立Skill和演示文件均包含在本仓库。`SHA256SUMS.json`核对分发文件；`scripts/package_plugin.py`重新打包当前插件内容并更新清单，`scripts/verify_distribution.py`验证清单、独立/内置Skill一致性、来源文件哈希和ZIP完整性。

`examples/verification.json`来自2026-10-08实际安装版本的验证，保留工具调用、合成数组、对象名称和输出文件哈希。为公开分发，安装路径和输出目录统一替换为符号占位，演示文件改用稳定名称，记录中标明该处理。原生项目和PNG保持原始字节。记录反映Windows本机测试，不代表其他机器或全部图型、字体、格式已验证。
