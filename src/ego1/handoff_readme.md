# EGo1 → PYNQ URX2：发送端开发交接

日期：2026-10-31。任务负责人：EGo1发送端由接收本包的队友编写；PYNQ的URX2固件、驱动、检测和界面已由主工程提供。本包足够独立编写发送程序，不要求接收方先理解整个PYNQ工程。

## 你要完成什么

在EGo1上实现一个可控的UART数据发生器，把同一串数据同时输出到扩展口B11和USB串口发送引脚T4。默认只在按S0后发送，支持9600/115200、8N1及8个指定场景。先保证正常帧精确，再实现故障注入，最后完成八路规则同帧触发场景。

数据使用**CAR-TLM1兼容的48字节二进制测试帧**，所有数据由EGo1合成，不连接电机，不改变小车固件。它与旧EGo1的`@LAB,...`文本程序是两个版本；不能把ASCII十六进制字符当成二进制字节发送。

本次只交接发送端开发资料，不包含已经完成的新版EGo1程序或bit，也不安排现在上板验证。PYNQ的URX2已通过离板验证，尚未完成实板验收；本包不包含PYNQ部署文件，联调时由主工程另行提供。

## 从这里开始

1. 阅读`docs/protocol_and_wiring.md`，严格按偏移、大小端和CRC定义编码。
2. 阅读`docs/test_scenarios.md`。P0八场景先做，P1三个扩展场景有余力再做。
3. 使用`fixtures/115200_parallel8_20s/`中的`stream.bin`、`bytes.mem`和发送时间表作为参考。可写实时编码，也可按ROM读取；不强制架构。
4. 复用`reference/rtl/uart_tx.sv`、`button_debounce.sv`和参考XDC。自己编写顶层、调度器、帧生成/ROM模块和自检testbench。
5. 在仿真中把**从UART TX线独立解码**出的字节保存为`received.bin`；不要直接导出生成器输入冒充串行线验证。
6. 用下面的工具核对，再按`docs/implementation_handoff.md`交回源码、构建入口及测试记录。

## 无板就能用的命令

解压后在包根目录运行，Python3.6或更新版本即可，所有工具只用标准库，不访问串口或板卡。

```text
python tools/verify_package.py
python tools/fixture.py check --fixture fixtures/115200_normal_20s --received received.bin --output check.json
python tools/fixture.py check --fixture fixtures/115200_parallel8_20s --received received.bin --starts frame_starts.csv --output parallel_check.json
python tools/fixture.py generate --case normal --baud 115200 --fps 50 --seconds 180 --output my_vectors/load_180s
```

第一条只检查包内文件摘要。第二条仅证明字节一致，输出`timing=NOT_CHECKED`；第三条还对照首帧对齐后的帧起始时间表，不替代testbench对每一位波特率、停止位和双输出一致性的检查。`frame_starts.csv`列为`slot,start_cycle`，单位为100MHz时钟周期，来源必须是自己的仿真输出。

## 包里有什么

| 目录 | 用途 |
|---|---|
| `docs/` | 协议、引脚、场景、实现约束和交回要求 |
| `profiles/` | 两份PYNQ协议/规则配置；线协议相同，规则不同；文件默认115200，9600用相应fixture下的`profile.json` |
| `fixtures/` | 已生成的8场景×2波特率、正常60秒、115200/50帧每秒正常60秒及3个P1扩展场景 |
| `tools/fixture.py` | 精确参考编码、向量生成、接收字节/帧时间表比较 |
| `tools/verify_package.py` | 包内摘要检查，不接硬件 |
| `oracle/uart_monitor/` | 主工程软件解析器、规则与硬件配置编译器的固定快照，仅供离线基准，不是PYNQ部署程序 |
| `reference/` | UART/按键复用模块、引脚约束、官方J5引脚图和创建工程模板；不含完整发送器 |
| `checks/` | 本包参考向量生成与独立解析核对结果；不是队友新RTL的仿真结果 |

## 两份配置不能选错

`ego1_faults.json`覆盖既有四条小车规则，再增加倾角越限持续100ms；用于正常、坏CRC、跳号、重复、断流、持续越限、毛刺等场景。

`ego1_parallel8.json`用8条独立规则槽比较同一个`fault_code`，阈值依次为0～7，均立即触发。场景111将其设为20，两次异常应得到2批、16条字段事件。这里验证的是**单UART输入的8路规则并行**，不代表8路UART，也不要求8个独立传感器。主工程已对这种配置完成RTL/软件等价核验。

## 当前边界

URX2候选构建为`release1`，100MHz布局布线通过，WNS=0.000ns、WHS=0.039ns。建立时间余量处于报告边界，实际稳定性、原板Python环境和实线吞吐量待板端联调。现阶段只编写并验证EGo1程序，不据此宣称URX2已上板通过。

不要将本包覆盖到已封存的旧URX1队友包。新EGo1程序用单独目录和新的文件名；不写配置Flash。联调前由双方确认加载的是URX2，PYNQ选择`FPGA并行规则 / URX2`和匹配的二进制配置。旧URX1同样能软件解码这些帧，但其结果不能作为URX2硬件规则验收。
