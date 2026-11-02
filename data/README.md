# 最新阶段验证数据

`pynq/` 按场景区分，保存原始字节、硬件时间戳、协议帧、硬件事件、前后窗口及原验收收据。收据中的绝对路径和状态反映原测试现场；文件内容未因目录迁移重写。运行 `python sim/verify_records.py` 可独立核验全部纳入的完整会话。

| 目录 | 范围 |
| --- | --- |
| `binary_acceptance` | EGo1 release2 与 startup2 的四轮新版二进制验收；另保留首轮波特率错误的失败记录，不能将其记作通过 |
| `power_recovery` | 正常关机并实际断电后，人工恢复的 200 帧/16 个完整设备故障窗口 |
| `car_live` | 300 秒、15028 帧的真实小车运行与 Notebook 联合检查；对应小车工程位于 `src/car/` |
| `text_acceptance` | 同一 bit 在 9600/115200 下接收文本，各 600 帧 |
| `failure_recovery` | 受控 FIFO 丢失和窗口保存失败/重试；保留前后状态，不归为正常采集 |

EGo1 的独立参考输入和发送端既有验证位于 `src/ego1/fixtures/`、`src/ego1/verification/`，避免与 PYNQ 的采集证据混淆。固定 `fixtures/` 下的输入是合成数据，不能视为真实小车测量。

回放校验只验证已有文件，不构成新增实板测试。故意注入 CRC、序号或本地采集故障的记录可能显示 FAIL，需按具体故障层级解释；不删除失败记录来形成全绿结果。


`car/synthetic_35s/` 是1750帧、84000字节的CAR-TLM1合成输入，供协议及双事件窗口离线核验。`pynq/startup_acceptance/` 是固定IP自动恢复和显式固件加载的有限基线实板验证。
