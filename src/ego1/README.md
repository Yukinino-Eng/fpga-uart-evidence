# EGo1 URX2 发送端：开发完成版

新开发的可控二进制 UART 测试源，与旧版 @LAB 文本发送器分别保存。顶层为 src/ego1_urx2_source_top.sv，器件 xc7a35tcsg324-1，默认 100 MHz、10 帧/秒。

## 板上操作

- SW0：OFF=9600，ON=115200。
- SW1：OFF=20 秒，ON=60 秒。
- SW4/SW3/SW2：000 正常、001 坏 CRC、010 跳号、011 重复、100 断流、101 持续倾角越限、110 短毛刺、111 八规则并行触发测试。
- 短按 S0 开始一整轮；发送期间的按键和开关变化不影响当前轮。完成后等待下一次 S0，不自动循环。
- S6/RST 可中止当前轮；中止的记录不作为完整通过。按下复位为低电平。
- D1_0=发送中，D1_1=不支持的配置错误，D1_2=本轮结束；D1_3/4/5/6/7 显示锁存的 SW0/1/2/3/4。故意注入坏 CRC 等数据异常不点亮配置错误灯。

B11（J5 物理 15）和 T4（板载 USB 串口）输出完全相同的 UART 流，只包含二进制帧。可先只接 USB 独立验证。接 PYNQ 时只接 B11/TX 和公共地，电平为 3.3 V；J5 33/34 是地，35/36 是电源，详细定位看原 docs/protocol_and_wiring.md。不同发送源不能并接同一个 RX。

## 实现

实时产生 44 字节帧体，逐位计算 CRC32/ISO-HDLC，加入 4 字节小端 CRC；无需场景 ROM。正常负数、有效标志、固定帧常量和故障注入与原 fixtures 完全一致。使用固定起始槽调度，不按“发完再等待”计时；elapsed、deadline、finish_cycle 均为 64 位。复用的 reference/rtl/uart_tx.sv 与 button_debounce.sv 未改动。

编译参数 FPS=50 可启用附加负载，9600/50Hz 请求会保持空闲并亮错误灯。FIXED_CASE=-1 使用开关；8/9/10 分别固定 status/invalid/restart 扩展。DURATION_SECONDS=0 使用开关，或固定为 20/60/180。

## 构建和自检

在包根目录运行，Vivado 安装路径由参数提供；脚本从自身位置寻找源码，不依赖本机项目绝对路径。新构建和新回归必须使用不同 label，避免覆盖记录。

~~~text
python scripts/run_build.py --vivado-bin D:/AMD/2025.2/Vivado/bin --label my_release
python tools/run_sender_tests.py --vivado-bin D:/AMD/2025.2/Vivado/bin --label my_sim
python tools/run_sender_extended.py --vivado-bin D:/AMD/2025.2/Vivado/bin
~~~

第三条使用固定 extended1 目录，重跑前请在新的包副本运行。50Hz 的新固件可用 --fps 50；固定扩展可用 --case 8；固定180秒可用 --seconds 180。默认固件为 firmware/ego1_urx2_release2.bit，参数 FPS=10、FIXED_CASE=-1、DURATION_SECONDS=0。

直接 Tcl 入口是 scripts/build.tcl，参数依次为 label、fps、case、duration。创建工程、综合、实现、100 MHz 时序检查和 bit 生成均在该脚本内；没有自动烧录或写 Flash。scripts/program_verified_board.tcl 是单独的临时 JTAG 加载脚本，只有显式执行才下载，并要求唯一目标、唯一 xc7a35t。加载后默认等待 S0。

## 验证证据

- verification/simulation4：25 项通过。八个 P0 场景 × 两档波特率、两档正常60秒、三项 P1 扩展、115200/50Hz 正常60秒、9600/50Hz 拒绝、两档100MHz短测。
- verification/extended1：3 项通过。180秒/50Hz/9000帧负载，以及两档100MHz引脚波形与字节短测。
- received.bin 来自 testbench 在 UART TX 引脚上的独立 8N1 采样；frame_starts.csv 来自引脚起始沿，没有导出生成器内部输入冒充接收。所有完整回归均通过 fixtures 逐字节和槽时间表核对；相对首帧时间偏差 0 周期。
- 完整场景为加速仿真：CLK_HZ=250000，观测周期转换为100MHz周期后与计划表比较；它验证完整序列、场景和调度，不能替代真实100MHz时钟下的60/180秒耐久运行。两档100MHz短测额外检查生产参数的串口位宽，分别为10417和868周期/bit。
- 默认固件在 Vivado 2025.2 生成，WNS=0.480 ns、WHS=0.122 ns，TNS/THS=0；779 LUT、700 FF、0 BRAM、1 DSP。DRC 无错误，保留 DPIP-1 与 DPOP-2 两条 DSP 流水线建议；CDC 为6条同步输入信息和1条复位同步信息，无警告/错误；无未约束内部端点。异步开关/按键和 UART/LED 端口没有外部同步时序预算，约束与报告中明确记录。
- 已将源码与约束复制到干净目录重新完整构建，得到相同时序结果。verification/clean_rebuild_summary.txt 与 clean_build.log 保存证据。

## 实板记录与范围

本次识别到唯一 xc7a35t，已通过 JTAG 临时加载默认固件；没有写 Flash。9600 与 115200 两档正常20秒实板 USB 接收均通过：各200帧、9600字节，逐字节与参考完全相同；已停止发送并关闭接收端口。当前 SW0=ON、SW1～SW4=OFF。USB 串口实际接收结果见 verification/board_* 中的 capture.json 和 received.bin。PC 读取完成时间不是硬件逐字节时间，不能用它证明 1 ms 调度误差。

本包是 EGo1 发送端的交回材料，不含 PYNQ URX2 部署。与 PYNQ 的接线、URX2 加载和事件窗口联调仍需独立验收。旧 URX1 能软件解码相同帧，也不能当成 URX2 硬件规则通过。原交接资料和 fixtures 保留供复核，输入包摘要保存在 verification/input_package_integrity.json，原文件清单另存 checks/input_manifest.sha256.json。
