# FPGA UART Evidence

基于 PYNQ-Z2 的 UART 异常监测与取证系统。FPGA 接收字节并附加硬件时间戳，最多八路规则并行检测，PS 保存事件前后窗口，Notebook 展示与回放数据。

工程包括 PYNQ URX2 startup2 接收端、EGo1 release2 合成测试发送端，以及实际验收使用的 STM32F103C8T6 小车工程。三套设备的工程与构建入口相互独立。PYNQ 只接收遥测，不控制小车。

## 工程目录

| 目录 | 内容 |
| --- | --- |
| `src/pynq` | 接收端 RTL、PS 软件、协议配置、Notebook、软件测试 |
| `src/ego1` | EGo1 合成 UART 发送器、约束、参考模型及测试向量 |
| `src/car` | 小车 C 源码、Keil 工程及保留固定参考页的链接脚本 |
| `board` | 三套设备的固件及部署、接线说明 |
| `sim` | 软件回归、原始数据回放与小车协议核验入口 |
| `data` | 实测原始数据、事件窗口与明确标注的合成输入 |
| `build` | 两套 FPGA 的独立重建入口及实现报告 |
| `report` | 设计报告、当前验证结论和文件版本清单 |
| `skill` | 项目协作与验证技能 |

小车 Keil 工程保留原始大小写路径，其他工程路径采用 ASCII 英文。编译缓存、调试器个人设置和本地认证脚本不属于发布内容。

## 电脑端检查

使用 Python 3.8+；Notebook 控件测试需要 ipywidgets、IPython 和 tornado。Windows 使用 PowerShell 7。

```sh
python sim/verify_repository.py
python sim/run_software.py
python sim/verify_records.py
python sim/verify_car.py
python src/car/tools/build.py --check-only
```

软件回归包含 88 项用例；3 项依赖未随包提供的可选测量记录，会明确跳过。数据回放使用 `data/` 中的完整会话，合成输入不会标为真实小车采集。

## PYNQ 部署与运行

```sh
python board/pynq/install_runtime.py --output /home/xilinx/jupyter_notebooks/uart_evidence
```

在板端终端对该运行目录配置一次持久 IP：

```sh
sudo /opt/python3.6/bin/python3.6 /home/xilinx/jupyter_notebooks/uart_evidence/scripts/pynq_fixed_ip.py
```

电脑与板卡使用相同网段，打开 `http://169.254.135.99:9090/tree`，进入实际运行目录的 `notebooks/uart_monitor.ipynb`。运行入口，选择协议和检测方式，依次点击“检查配置 → 加载通用接收固件 → 开始监测”。已核验系统镜像支持从默认 base.bit 显式恢复；未知镜像继续拒绝。详见 [PYNQ 部署](board/pynq/README.md)。

## Windows验收启动入口

完成上述部署后，双击工程根目录的`open_acceptance.cmd`。菜单1默认打开报告约定的`uart_evidence/notebooks/uart_monitor.ipynb`，菜单2和3查看实板回放，菜单5核验导出记录。需要PowerShell 7；记录核验另需Python 3.8+。

自检命令为`pwsh -File board/open_acceptance.ps1 -CheckOnly`。其他板卡地址和Notebook目录通过`-BaseUrl`与`-NotebookPath`指定，详见[验收电脑操作](board/acceptance_computer_operations.md)。

## 重建工程

FPGA 使用 Vivado 2025.2：

```sh
python build/rebuild.py --board pynq --vivado-bin D:/AMDDesignTools/2025.2/Vivado/bin --label my_build
python build/rebuild.py --board ego1 --vivado-bin D:/AMDDesignTools/2025.2/Vivado/bin --label my_build
```

小车使用 Keil MDK、ARM Compiler 5：

```sh
python src/car/tools/build.py --keil D:/Keil_32/UV4/UV4.exe
```

构建入口不下载固件，不操作电机。PYNQ 新构建的 bit/HWH 必须作为配对固件独立验证。小车固定参考页为 `0x0800FC00..0x0800FFFF`，下载时保留该页。

## 验证范围

- 真实小车运行与 Notebook 联合记录为 300 秒、15028 帧。
- EGo1 二进制输入覆盖 9600/115200、八路并行、持续越限和短毛刺。
- 同一 URX2 固件支持二进制 FPGA 规则和文本软件规则。
- 固定 IP 已完成一次实际断电自动恢复验证；默认启动镜像到 URX2 的显式加载分支已在实板通过。
- 本轮启动验证没有完整断电前文件快照，不代表全部历史文件一致性或新的外部信号采集验收。
- PYNQ 实现为 100 MHz，WNS=0.000 ns、WHS=0.044 ns；不声称额外时序裕量。

具体结果见 [验证清单](report/repository_validation.json)、[数据索引](data/README.md) 和 [设计报告](report/uart_evidence_design_report.pdf)。
