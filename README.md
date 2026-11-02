# FPGA UART Evidence

基于 PYNQ-Z2 的 UART 异常监测与取证系统：FPGA 接收并记录字节时间戳，最多八路配置化规则并行检测，PS 保存异常前后窗口，Notebook 展示实时状态并回放证据。

本仓库为 **2026-11-02 整理的最新工程快照**，接收端固定为 11 月 1 日已验收的 **URX2 startup2**，辅助发送端为 **EGo1 release2**。两块 FPGA 的源码、约束和构建入口独立。小车控制程序暂未上传；`car_telemetry.py`、`car_tlm1*.json` 与小车记录分别是 PYNQ 侧协议处理、配置和采集数据。

## 目录

| 路径 | 内容 |
| --- | --- |
| [src/pynq](src/pynq) | PYNQ 最新 RTL、PS 软件、协议配置、Notebook、板卡预设和回归用例 |
| [src/ego1](src/ego1) | 独立 EGo1 合成 UART 发送器、约束、参考模型、测试向量及验证记录 |
| [sim](sim) | 软件回归、原始数据独立回放、RTL 仿真说明 |
| [build](build) | 可复现构建入口及 PYNQ startup2 综合/实现报告 |
| [board](board) | 固件、运行目录部署脚本及上板说明 |
| [data](data) | 最新阶段实测原始数据、硬件事件、取证窗口及验收收据 |
| [skill](skill) | 九项项目协作与验证技能、来源索引及自检脚本 |
| [report](report) | 最新设计报告、实测补充、交互回放、文件来源和本次发布检查 |

文件路径均为 ASCII 英文；保留工具约定的 `README.md` / `SKILL.md`。中文说明只在文件正文中。工作缓存、旧版本工程、旧交付 ZIP、小车端源码和本地登录脚本未纳入。

## 电脑端复现

Python 3.8+ 用于电脑端检查；最新板端运行代码保留 Python 3.6 语法。Windows 使用 PowerShell 7。软件回归中的 Notebook 控件检查可使用现有 `ipywidgets` 环境；离线回放不需要连接板卡。

在仓库根目录执行：

```sh
python sim/verify_repository.py
python sim/run_software.py
python sim/verify_records.py
python skill/pynq-uart-verify/scripts/self_test.py
```

`run_software.py` 原样保留现有 79 项 UART 用例，其中 3 项依赖未收录的早期实板记录，会明确跳过；另一个入口直接核验本仓库最新数据。数据与旧收据中保留的原工作站路径是来源信息，不是复现所需路径。

查看 [八路及持续时间实测回放](report/replays/binary_acceptance.html) 或 [断电恢复后实测回放](report/replays/power_recovery.html)：先下载文件，再用浏览器打开。也可从原始记录生成新的交互页面：

```sh
python src/pynq/scripts/uart_monitor_view.py --record data/pynq/power_recovery/download/recovered_parallel8_115200_01 --output replay.html
```

## 重建与上板

使用 Vivado 2025.2，安装 Zynq-7000 和 Artix-7 器件支持。PYNQ 目标为 `xc7z020clg400-1`，EGo1 为 `xc7a35tcsg324-1`。

```sh
python build/rebuild.py --board pynq --vivado-bin /path/to/Vivado/bin --label my_build
python build/rebuild.py --board ego1 --vivado-bin /path/to/Vivado/bin --label my_build
```

Windows 的 `--vivado-bin` 例如 `D:/AMD/2025.2/Vivado/bin`。每次使用新 label。构建入口不烧写板卡；具体步骤见 [build/README.md](build/README.md)。原有已验收固件保持封存，新构建结果须单独验证。

PYNQ 部署为独立运行目录：

```sh
python board/pynq/install_runtime.py --output /home/xilinx/jupyter_notebooks/uart_evidence
```

再打开该目录的 `notebooks/uart_monitor.ipynb`。加载固件及基础镜像恢复方式见 [PYNQ 上板说明](board/pynq/README.md)；EGo1 的开关、接线和临时 JTAG 加载见 [EGo1 上板说明](board/ego1/README.md)。

## 已有验证和边界

- 最新 EGo1→PYNQ 二进制验收：9600/115200 八路并行、持续越限与单帧毛刺，四轮共 800 帧；恢复后再次验证 200 帧和 16 个完整设备故障窗口。
- 真实小车运行与实时 Notebook 联合检查：300 秒、15028 帧。PYNQ 只接收遥测，小车仍由原控制系统运行。
- 同一 URX2 固件接收两种协议；文本走 PS 软件规则，配置支持范围内的固定二进制走 FPGA 规则。
- 已有过载归因、保存失败重试和一次正常关机后断电、人工恢复的证据。未验证采集中突然断电、自动续采或 SD 卡容错。
- PYNQ 当前实现 100 MHz，报告 WNS=0.000 ns、WHS=0.044 ns；不能据此声称额外时序裕量或任意设备/满线速性能。
- EGo1 完成包记录了 28 组既有仿真；长时仿真使用加速时钟参数，两组短测使用真实 100 MHz。该区别保留在原验证记录中。

详情见 [最新设计报告 PDF](report/uart_evidence_design_report.pdf)、[可编辑 Word](report/uart_evidence_design_report.docx)、[数据索引](data/README.md) 和 [本次发布检查](report/repository_validation.json)。本次仓库整理的离线检查与既有实板验收分别记录。

