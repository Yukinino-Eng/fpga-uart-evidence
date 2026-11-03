# 验收电脑操作

## 准备与入口

Windows电脑安装PowerShell 7，保留工程目录结构，双击仓库根目录的`open_acceptance.cmd`。打开回放只需要浏览器；菜单5核验结果需要Python 3.8+。PYNQ部署及一次性固定IP配置见[板卡说明](pynq/README.md)。

| 编号 | 功能 |
| --- | --- |
| 1 | 打开PYNQ实时Notebook |
| 2 | 查看八路并行及持续时间的实板测试回放 |
| 3 | 查看同固件双协议的实板测试回放 |
| 4 | 查看本说明 |
| 5 | 独立核验导出ZIP或单个会话目录 |
| 6 | 查看固定IP与上电加载步骤 |
| 0 | 退出 |

## 按复现步骤打开实时界面

1. 按仓库README将运行目录安装至`/home/xilinx/jupyter_notebooks/uart_evidence`，配置一次固定IP。电脑有线口可使用`169.254.135.84/16`，板端使用`169.254.135.99/16`，双方地址不同，直连无需网关或DNS。
2. 启动菜单选择1，默认打开`http://169.254.135.99:9090/notebooks/uart_evidence/notebooks/uart_monitor.ipynb`。文件名为小写，和报告、安装器生成的文件保持一致。
3. 按系统卡实际方式登录Jupyter。点击入口代码单元格，按Shift+Enter。
4. 小车倾角演示选择“平衡小车 · 倾角异常演示”，115200，检测执行“FPGA并行规则 / URX2”。该配置检测有效倾角超出±10°并持续100毫秒；普通“平衡小车 · CAR-TLM1”用于基础遥测规则。
5. 点击“检查配置”，再点击“加载通用接收固件”。看到接收器保持停止后，确认接线并开始监测。
6. 查看车身倾角、状态和事件。两次异常之间恢复正常，系统会继续记录后续新触发。等前后窗收齐后停止接收，等待保存完成，再导出记录。

界面只接收遥测。车端使用配套CAR-TLM1：48字节、115200、8N1；运行与停止仍按小车原按钮流程操作。倾角动作演示保持电机停止。

## 其他地址和已有部署

在工程根目录运行以下命令，分别修改实际地址和Jupyter中的相对Notebook路径：

```powershell
pwsh -File board/open_acceptance.ps1 -Action live -BaseUrl http://192.168.2.99:9090 -NotebookPath uart_evidence/notebooks/uart_monitor.ipynb
```

已有startup2演示目录可继续使用：

```powershell
pwsh -File board/open_acceptance.ps1 -Action live -NotebookPath URX2_20261101_startup2_01/notebooks/UART_Monitor_Recovery.ipynb
```

入口自检核对配套文件并打印目标地址，不打开浏览器、不访问板卡：

```powershell
pwsh -File board/open_acceptance.ps1 -CheckOnly
```

上电后固定IP自动恢复，运行Notebook入口并显式加载固件，再开始新会话。若页面打不开，先访问`http://169.254.135.99:9090/tree`检查网络与目录。

## 回放与记录复核

菜单2和3打开的是已保存的实板测试记录，演示视频应标注“实板测试记录回放”。不连接EGo1也可查看。

停止并导出会话后，菜单5输入ZIP或会话目录的完整路径。核验读取原始字节、时间索引、配置和事件，在`out/acceptance_checks/`下新建核验结果，不改动原记录。也可以指定解释器运行：

```powershell
pwsh -File board/open_acceptance.ps1 -Action verify -PythonExe C:/Python313/python.exe -RecordPath C:/records/car_01.zip
```
