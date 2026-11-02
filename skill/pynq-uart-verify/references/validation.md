# 技能工具的实际验证范围

2026-11-01 统一版。机器可读收据为 [validation.json](validation.json)，与根目录的本轮收据一致。

## 已执行

- 六项 SKILL.md 均通过官方格式校验；检查本地引用和统一名称，实际主机 Python 版本见收据。
- 新路径下 self_test.py 的15项正负向自检通过，覆盖文件集合变化、路径/输出限制、时间长度与倒退、FAIL/UNKNOWN 和能力缺失的保持。
- check_project.py 的8例通过：7份已有物理采集、1份明确的20帧离线构造。核验字节/窗口摘要、时间和事件台账，并调用项目源码回放；过载仍保留采集 FAIL、设备 UNKNOWN。
- 新包的全新解压复核见与 ZIP 同名的 .validation.json 文件；解压后也可按下方命令自行复核。语法检查采用 Python3.6 口径，不代表已在板端 Python3.6 实测。

## 怎样复现

在解压后的 skill 目录运行：

```sh
python pynq-uart-verify/scripts/self_test.py
```

在另备的完整工程根目录运行，输出必须是新目录：

```sh
python skill/pynq-uart-verify/scripts/check_project.py --project-root . --output build/new_skill_check
```

没有完整工程和历史输入时，只能运行独立自检与通用文件工具；缺数据不能当作八例通过。

## 未验证范围

本轮没有连接板卡、执行 DMA 实测、从零重建 CAD 工程，或验证陌生队伍/第二块板卡迁移。前五项的方法规范化及历史收据核对，不等于这些工作流重新完成。协作案例不是完整聊天导出。

交付脚本仅用标准库；制作时官方格式检查器使用 PyYAML。Windows 受限临时目录曾导致旧版自检访问失败，本轮在允许临时文件访问的环境执行，没有修改系统目录权限。
