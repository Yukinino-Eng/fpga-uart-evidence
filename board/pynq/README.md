# PYNQ URX2 接收端

目标器件为 xc7z020clg400-1，FCLK0 为 100 MHz。使用本目录配对的 startup2 bit/HWH，摘要见 `report/provenance/pynq_version.json`。

## 部署

在仓库根目录执行 `python board/pynq/install_runtime.py --output <新的运行目录>`。脚本核验文件摘要，复制软件、协议、Notebook 和固件，不覆盖已有目录，也不连接硬件。板端沿用 PYNQ SDK、Python 3.6 和 ipywidgets 环境。

首次配置有线固定地址，在板端终端执行：

```sh
sudo /opt/python3.6/bin/python3.6 <运行目录>/scripts/pynq_fixed_ip.py
```

默认地址为 169.254.135.99/16；在 ifupdown 系统中增加开机别名 eth0:2，保留现有 DHCP、192.168.2.99、网关和 DNS。不重启网络，不操作 FPGA。已存在时可重复运行，冲突或不兼容系统会拒绝修改。电脑网卡应有同一网段的不同地址。撤销时运行同一命令并加 `--remove`，只移除匹配的持久配置，保留当前在线地址。

本系统卡的 Notebook 端口为 9090，其他镜像使用实际端口。打开 `http://169.254.135.99:9090/tree`，进入运行目录的 `notebooks/uart_monitor.ipynb`。

## 加载与采集

关闭其他硬件应用，运行 Notebook 入口。二进制选“FPGA并行规则 / URX2”，文本选“软件规则 / URX2通用”。选择协议与波特率，点击“检查配置”和“加载通用接收固件”，成功后再“开始监测”。加载成功会显示当前成功结果；开始监测只复用固件，不隐式下载。

显式加载按钮允许替换已核验的系统 base.bit，且只接受本包已核验的 startup2 bit/HWH。基础镜像 SHA256 为 `c15081be382e21c397684632e274558ce557c27df1e958daa83c1386205a54a3`。未知启动镜像或不匹配固件继续拒绝；现有接收器的运行、原始 FIFO、事件 FIFO 和检测器忙碌检查仍保留，并使用同一硬件锁。

同一固件已经加载时，可直接开始下一次监测。重跑入口前必须停止采集并完成保存；保存失败时先重试。接收端为 JA 第1脚/Y18，3.3 V UART、8N1，双方共地，一次只接一个 TX。真实小车使用 `car_tlm1.json` 或倾角演示配置，EGo1 八路场景使用 `ego1_parallel8.json`。

## 断电验收

先停止保存，使用同一新运行编号执行下面各阶段：

```sh
sudo /opt/python3.6/bin/python3.6 <运行目录>/scripts/urx2_power_acceptance.py --phase before --run power_check_01
```

通过后正常关机，待系统停止后再切电并重新上电。不要手动补 IP，不要先加载固件，先执行 `--phase after --run power_check_01`。通过后用 Notebook 按钮加载，或执行 `--phase load --run power_check_01`；最后在接收停止时执行 `--phase verify --run power_check_01`。

工具不自动修复网络，不自动开始采集，不覆盖成功收据。没有断电前快照时，只有使用此前实际记录的启动编号执行 `--phase observe --previous-boot-id <编号>` 才能做有限基线观察；结果不会声称完成全文件保存验证。真实信号采集还需开始监测、保存记录并独立回放。
