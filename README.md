# Data Analytics Portfolio | Wenshuo Cai

我的个人数据分析作品集，记录如何从公开数据出发，检查数据质量、定义指标、拆解变化并形成有证据支持的业务判断。代码、实际运行的 Notebook、聚合结果和分析备忘录均可查看。

**技术栈：** SQL · DuckDB · Python · pandas · Matplotlib · Jupyter

## 已完成项目

| 项目 | 分析问题与方法 | 阅读入口 |
|---|---|---|
| 淘宝用户行为分析 | 购买人数变化如何对应活跃规模、购买率与用户构成？用户级抽样、质量失败退出、对称分解、同星期参照、人群与严格加购路径分析。 | [案例说明](projects/taobao-user-behavior/README.md) · [Notebook](projects/taobao-user-behavior/analysis.ipynb) · [业务备忘录](projects/taobao-user-behavior/reports/business_memo.md) |

## 淘宝案例：主要发现

基于公开数据的用户样本，北京时间 2017-11-25 至 12-03 共 993,560 条行为记录、9,915 位用户。比较 12 月 1 日与 12 月 2 日：

- 购买用户从 **1,407 增至 1,747**，净增 340；活跃规模项 +416.75、购买率项 −76.75。
- 仅后一天活跃、两天均活跃、仅前一天活跃三组分别贡献 **+388、−9、−39** 位购买用户。
- 购买行为记录从 **2,096 增至 2,605**；品类正向增量 1,250、负向变化 −741。增长前十品类贡献正向增量的 **9.36%**。

![淘宝样本的每日活跃用户、购买用户与购买率](projects/taobao-user-behavior/outputs/daily_metrics.png)

这是公开数据的个人实践。购买记录不等于订单，仅后一天活跃不等于新注册，数量分解不证明促销或推荐策略的因果效果。详细口径、限制及两条复现路线见[案例 README](projects/taobao-user-behavior/README.md)。

新增分析显示 after_only 的 2,411 人全部在更早六天出现；严格加购商品对的后续购买率为 5.19%，高于 both_days 的 3.16%。这与用户购买率排序不同，提示需要区分分母、人群筛选和时间窗。完整证据见[业务备忘录](projects/taobao-user-behavior/reports/business_memo.md)。

[后续实验设计](projects/taobao-user-behavior/reports/experiment_design.md) 已完成方案撰写，**尚未实施**，没有实验提升结论。

## 后续项目方向

**计划中：UCI Online Retail 交易额与复购分析。** 先明确取消交易、负数量、客户标识缺失及完整月份口径，再分析购买客户数、频次与每笔金额的变化。目前尚未完成分析，未计入已完成项目。

## 浏览与复现

招聘方可直接阅读案例说明、业务备忘录和带输出的 Notebook，无需下载原始数据。复跑需要按[数据说明](projects/taobao-user-behavior/data/README.md)自行获取原 CSV，或使用已有 DuckDB 样本表。仓库只公开源代码、说明、聚合 CSV 和图表。
