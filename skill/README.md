# FPGA 监测工程技能包

2026-11-01 扩展统一版。当前可使用的九项技能均在本目录，每项以独立目录和 SKILL.md 为入口。三项用于选题、优化取舍和使用体验，六项用于实施与核验；历史指标分别标注，不互相替代。

## 技能索引

### 规划与体验

| 标准名称 | 讲什么、何时使用 | 主要失败条件 |
| --- | --- | --- |
| [fpga-project-plan](fpga-project-plan/SKILL.md) | 选择/重新评估题目，按用户价值、资源和工期收敛范围，形成可验证路线 | 价值无使用任务、主张无法观察、关键依赖无着落或范围失控 |
| [fpga-optimization-plan](fpga-optimization-plan/SKILL.md) | 依据瓶颈决定先优化哪一段、哪些任务放 FPGA，比较收益与代价 | 无瓶颈证据、比较条件不同、正确性/时序不满足或收益未验证 |
| [monitoring-ux-design](monitoring-ux-design/SKILL.md) | 按任务设计协议字段、实时状态、曲线和连续多故障记录 | 状态误导、事件难区分、人工操作阻断任务或显示改变证据 |

三项分别回答“做什么、为什么值得做”“下一步优化哪里”“怎样让使用者顺畅完成任务”。只有当前任务涉及这些决定时才采用，不因普通修错重新发起选题评估。案例均由真实协作与工程结果提炼；没有跨项目的决策收益实验，不把方法整理等同于实证成功。

### 实施与核验

| 标准名称 | 讲什么、何时使用 | 主要失败条件 |
| --- | --- | --- |
| [pynq-overlay-verify](pynq-overlay-verify/SKILL.md) | 加载、重连或重启后，核对固件配对、运行身份、空闲与访问锁 | 身份未知、摘要不符、锁占用或仍有活动数据 |
| [pynq-dma-verify](pynq-dma-verify/SKILL.md) | DMA 缓冲区、缓存一致性、帧长度/序号/校验与保存 | 所有权不明、超时、残帧、丢帧或保存失败 |
| [fpga-reference-verify](fpga-reference-verify/SKILL.md) | 用参考模型或协议契约验证改动，分开仿真/构建/实板/回放 | 参考差异、工具异常、缺日志或借用其他阶段 PASS |
| [fpga-release-verify](fpga-release-verify/SKILL.md) | 对目录/压缩包封存清单，在全新解压目录复核 | 内容改变、额外/缺失文件、越界路径或入口失败 |
| [pynq-runtime-debug](pynq-runtime-debug/SKILL.md) | 定位解释器、SDK、仿真进程、时间来源与固件混用 | 环境不明、异常原因未确认或缺修复后证据 |
| [pynq-uart-verify](pynq-uart-verify/SKILL.md) | UART 原始流回放、分层归因、多事件取证和保存重试 | 采集丢失、解析/事件通路错误、窗口不足或写盘失败 |

上述六项中，前五项主要整理旧阶段方法，第六项来自近期 UART 开发与实测。问题常交叠，但只采用本任务所需的流程：环境打不开先查 runtime，准备加载查 overlay，数据不完整按实际通路选 DMA 或 UART；修改 RTL 时用 reference；准备交接时用 release。

## 使用方法

把相应 SKILL.md 交给助手阅读，或将相应目录放入支持 SKILL.md 的技能位置，再用 `$fpga-project-plan` 等名称调用。本次只整理工程内文件，没有安装全局技能，也不修改生产固件、页面和报告。单项流程可独立阅读；根索引是来源追溯资料，八例项目回放另外依赖完整工程。

示例请求：

- “使用 $fpga-project-plan，评估现有监测项目是否应增加总线，给出价值、资源、验证成本和本次范围。”
- “使用 $fpga-optimization-plan，判断应该先做规则下沉还是页面提速，列出能验证瓶颈的最小实验。”
- “使用 $monitoring-ux-design，让操作者能读出每次故障的原因、触发时刻和保存状态，给出可走查的流程。”
- “使用 $pynq-uart-verify 核验这份记录，分别告诉我采集、协议、设备和保存状态。”

这些是新编调用示例，不冒充历史提示词。不要要求助手不分任务地执行所有硬件步骤。

九项正文均采用“用途与适用场景 → 输入与前置条件 → 执行步骤 → 失败条件与处理 → 输出与验收 → 来源与已验证效果 → 迁移边界与关联资料”，统一用事实、步骤和判据表述。历史结果、当前执行和未验证范围分别说明。三项新增技能各附 references/project-case.md，以真实转折说明判断和结果。

## 无板运行

原有交付脚本只用 Python 标准库，不需要 PYNQ、Vivado 或网络；按 Python3.6+ 语法编写。上一版实际运行环境见 [validation.json](validation.json)，没有在板端 Python3.6 新跑这些技能工具。新增三项是判断流程及案例，不附自动替用户打分或替代工程判断的脚本。

在本目录运行15项工具自检：

```sh
python pynq-uart-verify/scripts/self_test.py
```

封存自己的数据目录，清单必须位于源目录之外：

```sh
python pynq-uart-verify/scripts/check_snapshot.py create --root my_capture --manifest my_capture_manifest.json
python pynq-uart-verify/scripts/check_snapshot.py verify --root my_capture --manifest my_capture_manifest.json
```

该工具检测修改、新增及缺失，拒绝越界路径和符号链接，不覆盖现有输出。清单应另外保管或公布摘要；文件哈希不认证发布者身份。

下面命令在**完整工程根目录**运行，八例输入不包含在轻量技能 ZIP 内：

```sh
python skill/pynq-uart-verify/scripts/check_project.py --project-root . --output build/new_skill_check
```

输出目录必须为新目录。八例为两档八路规则、持续越限、短毛刺、过载、断电恢复后新采集、保存恢复，以及一份无校验/无序号离线构造；共7份历史物理记录和1份构造记录。过载记录继续保持采集 FAIL、设备 UNKNOWN，不能把“核验符合期望”理解为被测设备全部正常。

单例可以执行：

```sh
python skill/pynq-uart-verify/scripts/audit_record.py --project-root . --record build/uart_latest_binary_acceptance_20261101_01/download/parallel8_115200_02 --expect skill/pynq-uart-verify/examples/parallel8.json --output build/skill_checks/parallel8.json
```

`--project-root` 是被执行的可信本地工程源码；其他项目需替换解析/规则适配器。封存工具可以直接迁移，不意味着 URX2 文件格式适用于所有设备。

## 命名与旧版对应

技能名称及目录统一为“领域-对象-动作”的小写英文连字符形式，名称与 YAML 的 name 一致；显示标题用中文。参考文档及 JSON 用小写连字符，Python 脚本用下划线，固定入口保留 SKILL.md、README.md 和 agents/openai.yaml。

| 旧入口 | 当前标准入口 |
| --- | --- |
| pynq-overlay-load-and-verify.md | pynq-overlay-verify/SKILL.md |
| dma-capture-integrity.md | pynq-dma-verify/SKILL.md |
| golden-reference-regression.md | fpga-reference-verify/SKILL.md |
| release-self-verification.md | fpga-release-verify/SKILL.md |
| pitfalls-pynq-z2.md | pynq-runtime-debug/SKILL.md |
| pynq-uart-evidence/SKILL.md | pynq-uart-verify/SKILL.md |

旧目录 skill_pack_by_dafantong 是来源档案，不是另一套当前入口；旧技能 ZIP 保持原样，避免破坏已有摘要和引用。旧作者说明仅适用于原稿，当前九项整理与补充由 Codex 完成。原稿、历史收据与旧 ZIP 摘要见 [source-index.json](source-index.json)；原始文件仍在完整工程。案例中的用户原话来自本会话，没有另行补造模型原回答。

本次同时修正了容易误用的旧表述：HWH 与 XSA 不互换；Overlay 不重复下载；DMA 缓存操作依方向和驱动；残帧保留原始证据；旧版本 PASS 不替代新版本验收；SBB5 片内源 1MS/s 不当作 UART 性能。

## 验证及赛题范围

新增三项的格式、九项本地引用、来源摘要及旧六项文件未改动检查见 [decision-validation.json](decision-validation.json)。新版 ZIP 在新目录解压后核验完整清单；独立收据随 ZIP 以 .validation.json 提供。这些检查不等于新技能通过了外部用户的行为实验。

原六项工具的15项自检、8份历史记录核验及上一版解压结果见 [validation.json](validation.json) 与 [UART 工具说明](pynq-uart-verify/references/validation.md)。本轮未改这些脚本和原六项目录，保留原收据而不重复计数。没有重新执行 SBB/DMA 实板、CAD 重建或陌生队伍跨板复用。

按自由选题初级组指南整理的对应关系见 [contest-mapping.md](pynq-uart-verify/references/contest-mapping.md)。每项均交代失败/观察来源和已验证效果，但不承诺赛事加分。[collaboration-cases.md](pynq-uart-verify/references/collaboration-cases.md) 是实际协作摘要，不代替完整提示词、模型回答和自我纠错原文导出；不能补造缺失对话。
