# 来源、许可和验证边界

Origin COM控制实现来自：https://github.com/youngminsw/Origin-Pro-MCP 。

来源提交：https://github.com/youngminsw/Origin-Pro-MCP/tree/1e9741af96c45bcac9e619c3ba32264bac6950e7 。从本机检出目录复制的30个源文件与资源未经修改，实际文件哈希位于插件`server/PROVENANCE.json`。原项目`pyproject.toml`和`requirements.txt`曾在本机固定MCP低于2的依赖；发布快照保留本机依赖元数据和实际验证版本，不将其说成完全未改动的原始Git提交。

上游作者`youngminsw`的MIT声明位于插件`server/LICENSE`。本仓库自有插件说明、中文Skill和维护脚本适用仓库根目录MIT许可证，保留`zychen427`的声明。打包后插件同时保留其上游许可文件。

源清单、完整插件包、独立Skill和演示文件均包含在本仓库。`SHA256SUMS.json`核对分发文件；`scripts/package_plugin.py`重新打包当前插件内容并更新清单，`scripts/verify_distribution.py`验证清单、独立/内置Skill一致性、来源文件哈希和ZIP完整性。

`examples/verification.json`来自2026-10-08实际安装版本的验证，保留工具调用、合成数组、对象名称和输出文件哈希。为公开分发，安装路径和输出目录统一替换为符号占位，演示文件改用稳定名称，记录中标明该处理。原生项目和PNG保持原始字节。记录反映Windows本机测试，不代表其他机器或全部图型、字体、格式已验证。
