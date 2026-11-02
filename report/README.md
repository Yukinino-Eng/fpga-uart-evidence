# 报告与验证资料

- `uart_evidence_design_report.docx` / `.pdf`：系统设计、协议、实现及验证报告。
- `pynq/`：当前功能、测量结果与部署要求。
- `replays/`：可独立打开的八路规则和取证窗口回放。
- `provenance/pynq_version.json`、`car_version.json`：接收端和小车文件版本。
- `repository_validation.json`：发布文件实际完成的检查及验证范围。

仓库根目录 `manifest.sha256.json` 覆盖当前发布文件，清单自身不列入。实测数据与合成输入分别标识，不将文件回放、寄存器模型或软件回归视为新增实板采集。
