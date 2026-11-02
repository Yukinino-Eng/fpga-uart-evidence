# 开发与环境记录

最初 Vivado MCP 启动因工具环境缺少 PROCESSOR_ARCHITECTURE 而退出；当前仅在本地工具子进程中补齐 AMD64，未改系统环境。后续直接使用同一 Vivado 2025.2 / XSim 完成构建与仿真。

开发时修复了验证脚本中的 Windows 批处理引号、Tcl 路径分隔符、仿真默认 timescale，以及 testbench 字符串文件名构造问题；失败日志保留在工作目录 verification/simulation1～3。最终完整回归为 simulation4，所有字节与时间比较通过；未降低检查标准或修改原 fixtures 来取得通过。

默认硬件构建 release2 与干净目录 portable1 的源码/约束一致，均为 WNS=0.480ns、WHS=0.122ns。独立USB实板记录与仿真记录分别标记来源。
