# EGo1：release2 合成 UART 发送端

独立工程位于 `src/ego1/`，器件为 `xc7a35tcsg324-1`。封存固件为 `src/ego1/firmware/ego1_urx2_release2.bit`，不与 PYNQ 固件混用。详细实现、场景及已有验证见 [发送端 README](../../src/ego1/README.md)。

- SW0：OFF=9600，ON=115200。
- SW1：OFF=20 秒，ON=60 秒。
- SW4/SW3/SW2：000 正常、001 坏 CRC、010 跳号、011 重复、100 断流、101 持续倾角越限、110 单帧毛刺、111 八路并行。
- S0 开始一轮，结束后等待下一次按键；S6/RST 中止当前轮。

UART 输出 B11/J5 第 15 脚，3.3 V，8N1，与 PYNQ 共地并接至 JA 第 1 脚/Y18。USB 串口 T4 同步输出，可独立检查发送字节。EGo1 是合成验证源，不能当作第二台真实设备。

仅在需要临时 JTAG 配置时显式执行：

```sh
vivado -mode batch -source src/ego1/scripts/program_verified_board.tcl
```

该入口要求唯一的 Artix-7 目标，加载后等待按键；不写 Flash。本次整理未连接或重新烧写板卡。

