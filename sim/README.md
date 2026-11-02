# 验证入口

从仓库根目录运行：

```sh
python sim/verify_repository.py
python sim/run_software.py
python sim/verify_records.py
```

第一项验证发布文件 SHA256、路径规范和配对固件。第二项运行原有 UART 软件回归，依赖旧记录的三项明确跳过。第三项使用独立软件规则重新解码本仓库的最新采集记录，核对文件摘要、硬件事件及窗口；对于故意过载的数据，按驱动记录的采集故障边界返回归因状态，不把它当成正常数据。

RTL 仿真入口保留在两套独立工程内。PYNQ 在 `src/pynq` 下运行：

```powershell
pwsh -NoProfile -File scripts/run_urx2.ps1 -Stage sim -PythonExe python -VivadoPath D:/AMD/2025.2/Vivado/bin/vivado.bat -Label sim_new
```

startup2 连续流启动回归可另执行 `vivado -mode batch -source scripts/simulate_uart_startup.tcl -tclargs startup_new`。不要启用 `baseline` 参数，该历史失败版本未收录。

EGo1 在 `src/ego1` 下运行：

```sh
python tools/run_sender_tests.py --vivado-bin /path/to/Vivado/bin --label sim_new
```

EGo1 扩展回归 `tools/run_sender_extended.py` 使用固定 `extended1` 输出路径；本仓库已带既有结果，应在独立副本中移出该结果目录后运行，以保留原记录。既有仿真和实板证据不表示本次整理重新执行了 RTL 或硬件验证。

