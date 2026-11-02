# 构建入口

从仓库根目录运行 `python build/rebuild.py --board pynq|ego1 --vivado-bin <Vivado 的 bin 目录> --label <新的英文标签>`。推荐 Vivado 2025.2，与已有实现记录一致。

- PYNQ：执行 `src/pynq/scripts/build_urx2.tcl`，从 RTL、板卡预设和约束重建 PS7/AXI Block Design；输出到 `src/pynq/build/pynq_z2/uart_detector2/<label>/firmware/`。
- EGo1：执行独立的 `src/ego1/scripts/build.tcl`；默认 100 MHz、10 FPS、开关选择场景；新 bit 位于 `src/ego1/firmware/ego1_urx2_<label>.bit`，新报告位于其 `verification/<label>/`。

使用新标签以保留已有结果。入口不连接 Hardware Manager，不写 Flash，不覆盖已验收固件。已有 PYNQ startup2 的报告在 `build/pynq/reports/`，EGo1 release2 报告在 `src/ego1/verification/release2/`。报告中的原始绝对路径为当时运行记录。

本次发布整理没有重新执行综合、实现或实板测试；具体离线核验结果见 `report/repository_validation.json`。

