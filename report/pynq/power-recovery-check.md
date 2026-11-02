# 启动与恢复验证

本系统卡已验证固定地址169.254.135.99/16在一次实际断电后自动恢复，Notebook 9090端口可访问。默认base.bit经过身份摘要核验后，可通过显式加载分支恢复本包URX2 startup2，硬件身份、ABI、时钟和空闲状态检查通过。

启动验证结果见 `data/pynq/startup_acceptance/`。该组记录没有完整断电前文件快照，范围为固定地址与显式固件恢复，不代表全文件保存验证或新的外部信号采集。

标准复测使用 `scripts/urx2_power_acceptance.py` 的 before、after、load、verify 阶段。先观察网络和启动镜像，再允许加载；失败不自动补地址、不覆盖收据。运行步骤见 `board/pynq/README.md`。
