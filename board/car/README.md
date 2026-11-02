# 小车固件与连接

`firmware/Lesson20Uart.hex` 和 `.axf` 与实际验收工程提供的固件字节一致。源码与 Keil 工程位于 `src/car/`。常规下载使用 HEX；AXF 包含调试符号。

USART1 PA9 TX 接 PYNQ JA 第 1 脚/Y18，双方公共地。小车和 PYNQ 分别供电，不连接排针电源，不将两个发送端并接。参数为 115200、8N1、48 字节 CAR-TLM1、约 50 Hz。

PYNQ 选择“FPGA并行规则 / URX2”和对应小车协议。PYNQ 仅读取遥测，小车仍由原有按钮控制。重新构建、固定参考页保留及字段语义见 [小车工程说明](../../src/car/README.md)。
