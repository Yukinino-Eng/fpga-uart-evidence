# PYNQ-Z2：URX2 startup2

FPGA 为 `xc7z020clg400-1`，FCLK0 为 100 MHz。此目录固件来自 2026-11-01 已验收封存快照；bit/HWH/XSA 的摘要位于根目录 `manifest.sha256.json` 及 `report/provenance/pynq_version.json`。

运行 `python board/pynq/install_runtime.py --output <新的运行目录>`，脚本只复制运行文件，不连接或修改硬件，不覆盖已有运行目录。然后从该目录打开 `notebooks/uart_monitor.ipynb`。Notebook 输出已清理，运行单元与封存版本一致。

固件和程序在部署后同处一个运行目录，避免开发机目录结构影响板端查找。PYNQ 环境沿用既有 PYNQ SDK、Python 3.6、ipywidgets 7.2.1；电脑可用较新 Python 做离线验证。不要为运行本工程自行升级整张系统镜像。

接收线为 PYNQ JA 第 1 脚，器件管脚 Y18，3.3 V UART，8N1；双方共地。EGo1 发送线为 B11/J5 第 15 脚。一次只接一个 TX，接线依据分别在两块板的约束文件中。小车 TX 仅为被监测信号，不由 PYNQ 控制。

在 Notebook 选择 FPGA 检测与二进制配置；合成八路场景选 `ego1_parallel8.json`，真实小车选 `car_tlm1.json` 或经过确认的倾角演示配置。文本协议选软件规则/URX2 通用模式。启动后保存的记录仍由原始字节、时间戳索引和事件窗口组成。

驱动有硬件身份和空闲检查。如果整机刚启动、PL 是系统默认 base.bit，先按 [已有断电恢复步骤](../../report/pynq/power-recovery-check.md) 核对基础镜像和固件，再显式恢复。步骤中的 `root` 改为实际部署路径；基础镜像摘要不同则需要独立核验，不能直接套用旧摘要。既有证据只覆盖一次正常关机后的人工恢复。

