# 淘宝用户行为分析：购买人数变化

这个项目分析淘宝公开行为日志中一次购买人数变化：2017 年 12 月 2 日购买用户比前一天增加了 340 人，但活跃用户购买率下降了 0.89 个百分点。分析先拆解活跃规模与购买率的变化，再检查两天用户构成、品类增量和加购后的购买路径。窗口内共有 993,560 条行为记录、9,915 位用户，结论仅针对这份公开样本。

先看[业务备忘录](reports/business_memo.md)了解证据与解释，或打开[Notebook](analysis.ipynb)按步骤查看查询和实际输出。

数据来自[天池淘宝用户购物行为数据集](https://tianchi.aliyun.com/dataset/649)，观察窗口为北京时间 **[2017-11-25 00:00, 2017-12-04 00:00)**。这是使用公开数据的个人项目。

## 主要发现

| 指标 | 2017-12-01 | 2017-12-02 | 变化 |
|---|---:|---:|---:|
| 活跃用户 | 7,456 | 9,718 | +2,262，+30.34% |
| 购买用户 | 1,407 | 1,747 | +340，+24.16% |
| 活跃用户购买率 | 18.87% | 17.98% | −0.89 个百分点 |
| 购买行为记录 | 2,096 | 2,605 | +509 |

- **活跃规模扩大，购买率下降。** 根据“购买人数＝活跃人数×购买率”做对称分解，活跃规模项为 +416.75，购买率项为 −76.75，合计 +340。两项是折算人数，表示数量关系。
- **人群变化主要来自前一天未活跃的人。** after_only（12 月 1 日未活跃、12 月 2 日活跃）、both_days（两天均活跃）、before_only（两天中仅前一天活跃）分别贡献 +388、−9、−39 位购买用户。after_only 的 2,411 人全部在 11 月 25—30 日出现过，不能将其称为新注册用户或长期沉默用户。
- **购买记录的增长分散在多个品类。** 两天至少一天有购买的 1,345 个品类中，709 个增长、491 个下降、145 个持平。正向增量 1,250、负向变化 −741，净增 509 条；前十增加 117 条，占正向增量 9.36%。
- **同星期参照也呈现人数上升、购买率下降。** 同周六（11 月 25 日 → 12 月 2 日）购买人数 1,349 → 1,747，购买率 18.91% → 17.98%（−0.94 个百分点）；同周日（11 月 26 日 → 12 月 3 日）购买人数 1,375 → 1,725，购买率 19.09% → 17.78%（−1.31 个百分点）。九天数据只能提供有限参照，不能建立稳定季节性基线。
- **加购路径与日用户购买率给出不同的人群排序。** 24小时加购商品对后续购买率：after_only 为 77/1,485＝5.19%，both_days 为 188/5,953＝3.16%；对应日用户购买率分别为 16.09%、18.60%。两种指标的人群、分母和时间窗不同，不能据此判断用户质量或产品路径是否存在故障。

12 月 2 日、3 日分别有窗口内全部样本用户的 **98.01%、97.85%** 活跃，分母均为 9,915 人。这是样本活跃占比，不是平台渗透率；接近全样本活跃，需要核查来源的用户入选规则和采集范围。

## 关键图表

![每日活跃用户、购买用户与购买率](outputs/daily_metrics.png)

![样本活跃占比与加购路径](outputs/context_diagnostics.png)

## 核心口径与限制

- 固定 DuckDB **1.5.5**，五个原始字段均以 `VARCHAR` 读取；按 `hash(user_id) % 100 = 0` 抽取约 1% 的用户，保留入选用户的全部可见记录。[DuckDB hash 可能随版本变化](https://duckdb.org/docs/current/sql/functions/utility#hashvalue)，因此复现需要相同版本，不能把结果直接放大为全平台估计。
- 原样本 994,112 条，排除窗口前 526 条、窗口后 26 条有效记录，保留 993,560 条。五字段完全相同的多余记录为 1 条，因缺少唯一事件编号而保留并披露。
- 活跃用户是当天出现任意合法行为的去重用户；购买用户是当天出现 `buy` 的去重用户；活跃用户购买率＝购买用户／活跃用户；购买行为记录是 `buy` 的行数。记录不等于订单，数据无金额字段，不能计算 GMV。
- 加购路径以 12 月 2 日每个用户—商品对的首次加购为起点 `t0`，检查同用户、同商品在 `(t0, t0+24h]` 是否出现购买，每对最多计一次成功。分母是有完整观察范围的去重商品对，要求 `t0+24h` 严格早于窗口右端。同秒购买不能单独作为先后证据，观察不足的起点排除并披露；没有合格商品对时比率留空。

原始行为字段保留，质量检查与指标统一使用去除首尾空白后的值；已保存样本的规范化记录数和致命质量问题数均为 0。完整的字段规则、失败拦截与旧输出保护见[复现说明](reports/reproduction_checks.md#质量规则与文件保护)，具体查询及选择理由见 Notebook。

对称分解公式为：

```text
Δ购买人数 = Δ活跃人数 × 两日购买率均值
           + Δ购买率 × 两日活跃人数均值
```

这些结果描述样本中的变化，不能确定促销、推荐或周末造成了增长。每日覆盖 24 个小时的记录也不能证明采集完整。

## 阅读入口

| 文件 | 内容 |
|---|---|
| [业务备忘录](reports/business_memo.md) · [Notebook](analysis.ipynb) | 先读结论与证据，再逐步查看查询和输出 |
| [analysis.sql](analysis.sql) | 质量检查、日指标、人群、品类和加购路径查询 |
| [prepare_data.py](prepare_data.py) · [run_analysis.py](run_analysis.py) | 原 CSV 抽样入口与下游分析入口 |
| [数据说明](data/README.md) | 来源、字段及下载说明 |
| [outputs](outputs/) | 13 份聚合 CSV 与 2 张图，含同星期比较、人群历史和加购路径 |
| [复现说明](reports/reproduction_checks.md) | 执行环境、验证记录、测试覆盖与边界 |

## 运行与验证

### 环境与启动目录

从仓库根目录进入案例目录，执行以下命令。本地根目录可以继续叫 `taobao_analysis`，不必与远程仓库同名。

```bash
cd projects/taobao-user-behavior
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m ipykernel install --user --name taobao-analysis --display-name "Python (taobao-analysis)"
```

Windows 使用 `.venv\Scripts\activate` 激活环境。核心分析包固定版本，Jupyter 辅助工具给出兼容范围，见 [requirements.txt](requirements.txt)。下文命令均从案例目录执行。

### 路线 A：从原始 CSV 开始

从来源页下载并解压无表头的 `UserBehavior.csv`，放入 `data/`。两步依次完成原 CSV 读取与用户抽样，再进行质量检查、窗口筛选、分析与导出：

```bash
python prepare_data.py --csv data/UserBehavior.csv --db data/taobao.duckdb
python run_analysis.py --db data/taobao.duckdb --output outputs
```

也可运行 `jupyter lab analysis.ipynb`，选择上述环境，从头执行。Notebook 在数据库文件不存在时建立样本；已有文件必须包含符合字段约定的 `sample_events`。前几个单元预览 CSV 字段，因此 Notebook 仍需要原 CSV。

`prepare_data.py` 拒绝覆盖已有数据库。确需重新抽样时，指定新的 `--db` 文件名，保留原数据和既有样本。

### 路线 B：复用已有样本

已有数据库只需包含五列均为 VARCHAR 的 `sample_events`。先关闭其他进程对同一数据库的连接（Notebook 中可执行 `con.close()`），再运行：

```bash
python run_analysis.py --db data/taobao.duckdb --output outputs
```

该脚本从既有样本开始，不读取原 CSV；它不能代替路线 A 的抽样步骤。脚本和 Notebook 均以只读方式打开已有数据库，只创建临时派生表。

### 兼容本地旧文件位置

原 CSV 和数据库已在仓库根目录时，无需移动或复制。从案例目录可直接运行：

```bash
python run_analysis.py --db ../../taobao.duckdb --output outputs
```

Notebook 优先使用 `data/UserBehavior.csv`，不存在时识别 `../../UserBehavior.csv` 并使用同目录数据库。macOS / Linux 也可显式指定相对路径：

```bash
TAOBAO_CSV=../../UserBehavior.csv TAOBAO_DB=../../taobao.duckdb jupyter lab analysis.ipynb
```

`--csv` 可指向其他位置的原文件；Notebook 可用 `TAOBAO_CSV`、`TAOBAO_DB`、`TAOBAO_OUTPUT` 指定输入和输出。请顺序执行，质量检查失败后不要跳过单元继续使用旧变量。

### 回归测试

```bash
python -m unittest discover -s tests -v
```

8 项测试覆盖行为规范化、质量失败、旧输出保护、重复保留、历史与加购时间边界、用户 hash 抽样，以及 Notebook 品类贡献率的零分母和正常分母情况。测试使用合成输入，不接触真实原库，详见[测试与执行记录](reports/reproduction_checks.md)。

## 后续工作

先核查源数据入选与采集范围，再补充访问来源、曝光、商品和策略记录，判断人群差异的可能解释。[加购商品回访入口实验草稿](reports/experiment_design.md) 的状态为 **“方案设计，尚未实施”**；同口径基线、业务阈值和必要埋点仍待补充。
