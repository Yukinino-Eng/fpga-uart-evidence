# PYNQ 断电后人工恢复验收

2026-11-01，使用同一张系统卡、同一份 URX2 startup2 bit/HWH 完成一次实际断电、重新上电和人工恢复。该记录覆盖正常关机后的恢复，不覆盖采集中突然拔电或存储卡损坏。

## 已验证的过程

1. 停止采集，确认原始 FIFO、事件 FIFO 和硬件执行状态均为空闲；对 1228 个运行程序、配置及历史结果文件建立 SHA256/大小快照，执行磁盘同步。
2. 用户拔下 EGo1 TX 信号线，保留公共地。系统正常关机，串口记录到文件系统卸载和 `reboot: System halted`。
3. 用户切断 PYNQ 电源，等待约 5 秒后重新上电，SD 卡、BOOT 的 SD 档、网线与 USB 保持原样。
4. Linux 启动编号从 `94a52731-3473-4170-81fd-45c88a1ff22e` 变为 `bdc830fa-3c7f-4bec-b0e3-964f9e7ed677`，证明确实重新启动。
5. 原 1228 个文件和 Notebook 源码均通过重启后校验。9090 Notebook 服务自动启动；临时 `169.254.135.99/16` 地址未保留，通过控制台手动恢复。
6. PL 启动时是系统默认 base.bit，未自动恢复 URX2。核对基础镜像和目标 bit/HWH 摘要后显式加载 URX2，接收仍停止。
7. 在实际 Notebook 中打开断电前的 200 帧、18 个窗口历史记录。用户接回 EGo1 TX，重新运行 115200、20 秒八路场景。
8. 新会话 200 帧、9600 字节与队友封存参考流逐字节一致；两批各八条规则使用同一批硬件时间戳触发，16 个设备故障窗口均完整保存并回读通过，电脑独立回放一致。启动等待和发送结束后另有两条超时记录，分别保存实际可用范围。
9. 再次核对原 1228 个文件未变；停止接收，两个 FIFO 均为空，所有接收/校验/序号错误及溢出计数为零。

硬件时间为本次运行的相对时间；重启重新加载后时间基准重新开始，各会话分别归档，不将旧时间戳拼接为连续 UTC。

## 同一系统卡的恢复操作

先正常关闭系统再切电。断电前拔下外部 TX，等 PYNQ 恢复供电、软件和固件后再接回；被测设备始终由原有实体按钮操作。

本机电脑以太网当前为 `169.254.135.84/16`。这轮系统卡开机默认地址是 `192.168.2.99/24`，临时别名未持久化。若当前网络无法访问，通过 COM5、115200、8N1 登录控制台，查看 `ip -4 addr show dev eth0`，确认没有该临时地址时运行：

```sh
sudo ip addr add 169.254.135.99/16 dev eth0
```

本次访问地址：`http://169.254.135.99:9090/notebooks/URX2_20261101_startup2_01/notebooks/UART_Monitor.ipynb`。本轮 9090 服务自行启动；该事实只针对本张系统卡，不能推广到其他 PYNQ 镜像。

现有通用驱动会拒绝覆盖身份未知的启动 overlay。因此从系统默认 base.bit 恢复时，需先做以下显式恢复；普通已加载 URX2 的再次采集不需要此步骤。以下代码从本轮实际执行的恢复检查提炼，仅适用于这份已核验的基础镜像和固件。先关闭其他硬件应用，保持 TX 断开，并使用有硬件权限的 Python 3.6 环境：

```python
from pathlib import Path
import hashlib
import sys
from pynq import PL, Clocks, Bitstream

root = Path('/home/xilinx/jupyter_notebooks/URX2_20261101_startup2_01')
sys.path.insert(0, str(root / 'scripts'))
from pynq_hardware_lease import HardwareLease
from uart_monitor.urx2 import URX2Transport
from uart_monitor.profile import load_profile

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

base = Path('/opt/python3.6/lib/python3.6/site-packages/pynq/overlays/base/base.bit')
bit = root / 'firmware/uart_detector2.bit'
assert PL.bitfile_name == str(base), '非预期启动应用，保留现场，不覆盖'
assert sha256(base) == 'c15081be382e21c397684632e274558ce557c27df1e958daa83c1386205a54a3'
assert sha256(bit) == '24870758d42c9abcbf5bf7ffc631dfbfb8de886d512fd5d10e403cfdfae4106f'
assert sha256(bit.with_suffix('.hwh')) == 'f6f7ab1713720150fc2dccd42cfc31d2c9fdb47c84bec42999d50f3172421edf'
with HardwareLease():
    assert PL.bitfile_name == str(base)
    Clocks.fclk0_mhz = 100
    Bitstream(str(bit)).download()
    receiver = URX2Transport(bit, load_profile(root / 'profiles/car_tlm1.json'))
    state = receiver.registers()
    assert all(state[k] == 0 for k in ('control', 'level', 'event_level', 'hardware_active'))
    receiver.close()
print('URX2已恢复，接收保持停止。')
```

之后运行 Notebook 单元格，选择协议、检测执行方式与波特率，再开始新会话。小车二进制使用实际小车配置；八路合成测试使用 `ego1_parallel8.json` 和 FPGA 规则；LAB 文本使用“软件规则 / URX2通用”。不得把两个 TX 并接。

## 证据与边界

本地证据目录：`build/uart_power_recovery_20261101_01/`。

- `before.json` 与 `board_receipts/`：断电前后文件快照、启动编号、临时网络恢复、显式加载和最终状态。
- `console.log`：正常关机和部分 SD 启动日志。初始监听遇到电脑 GBK 输出编码错误，已保留失败并修正；不能称为完整启动日志。新启动编号与后续板端检查另行证明恢复。
- `browser_initial_failure.json`：历史界面替换 iframe 时的自动化观察失败；修正观察方式后复核通过，不是采集故障。
- `notebook_recovery.json`、`historical_record_after_boot.png`：实际 Notebook 旧记录打开结果。
- `download/recovered_parallel8_115200_01/`：新会话原始流、时间索引、解析帧、硬件事件、窗口及报告。
- `recovered_parallel8_115200_01_verification.json`：参考字节、窗口完整性和电脑独立回放。
- `completion.json`：本轮最终汇总。

本轮是一次正常关机后的人工恢复，不代表自动断电续采、任意断电点文件原子性、SD 卡耐久或反复冷启动可靠性。没有更新系统卡、QSPI、小车程序或控制参数。
