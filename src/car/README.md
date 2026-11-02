# STM32 平衡小车工程

本目录为实际验收所用的小车工程，目标为 STM32F103C8T6。控制与遥测源码、Keil 工程及链接脚本保持提供文件的字节内容。固件位于 `board/car/firmware/`，版本摘要见 `report/provenance/car_version.json`。

在仓库根目录检查依赖：

```sh
python src/car/tools/build.py --check-only
```

用 Keil MDK ARM Compiler 5 打开 `Project.uvprojx`，选择 `Lesson20 UART PYNQ` 并 Rebuild，或执行：

```sh
python src/car/tools/build.py --keil D:/Keil_32/UV4/UV4.exe
```

Keil 路径按实际安装修改。脚本只重建，不下载、不操作电机。生成固件位于 `src/car/build/firmware/`。应用镜像不占用末尾 `0x0800FC00..0x0800FFFF` 固定参考页；下载时按实际编程器配置保留该页。

遥测为 CAR-TLM1：48 字节、115200 / 8N1、20 ms 周期，CRC-32/ISO-HDLC 覆盖前 44 字节。USART1 PA9 为发送端，接 PYNQ JA 第 1 脚/Y18，双方共地、3.3 V 电平。一次只连接一个 TX；PYNQ 不控制小车。

接收使用已有 `car_tlm1.json`；倾角演示使用 `car_tlm1_tilt_demo.json`。姿态无效时使用 `INT32_MIN` 与有效位，接收侧保留无效状态。PWM 上报真实 TIM3 CCR 计数，原小车周期为 100 计数；不做缩放。此工程未启用独立硬件看门狗，遥测 flags bit4 为 0，原有软件保护逻辑仍保留。

按键控制：第一次短按进入平衡，第二次短按执行前进任务；前进中按下停止，平衡中长按约 1 秒停止，空闲长按保存参考。实际车辆运行按既有机械、电源与场地要求操作。

随包的 35 秒输入是离线合成测试数据，不是真实车辆采集。可在仓库根目录运行 `python sim/verify_car.py` 验证协议、字段与独立事件窗口。
