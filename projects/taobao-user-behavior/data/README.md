# 数据来源与本地文件

来源：[天池淘宝用户购物行为数据集](https://tianchi.aliyun.com/dataset/649)。请在来源页按当前下载流程获取数据（可能需要登录），解压得到 `UserBehavior.csv`。本仓库不提供原始事件数据、用户明细或下载压缩包；使用原数据时遵循来源页条款。

本案例使用的文件约 3.4 GiB，无表头，字段顺序如下：

| 字段 | 读取类型 | 含义 |
|---|---|---|
| user_id | VARCHAR | 匿名用户标识，用于用户抽样与去重 |
| item_id | VARCHAR | 匿名商品标识 |
| category_id | VARCHAR | 匿名品类标识，没有名称映射时仅使用编号 |
| behavior_type | VARCHAR | `pv` 浏览、`cart` 加购、`fav` 收藏、`buy` 购买行为 |
| timestamp | VARCHAR，分析时转换为 BIGINT | 秒级 Unix 时间戳，转换到 Asia/Shanghai 后按日分析 |

建议将 CSV 放在此目录，生成的数据库也默认保存在这里：

```text
data/
├── README.md          # 公开
├── UserBehavior.csv   # 本地，Git 忽略
└── taobao.duckdb      # 本地，Git 忽略
```

原 CSV 已在仓库根目录时无需复制，通过 `--csv ../../UserBehavior.csv` 或 Notebook 的 `TAOBAO_CSV` 指向它即可。已有根目录数据库通过 `--db ../../taobao.duckdb` 读取。命令均从 `projects/taobao-user-behavior` 执行，完整步骤见[案例说明](../README.md)。

本案例固定使用 DuckDB 1.5.5、VARCHAR 用户 ID 和 `hash(user_id) % 100 = 0`，不是逐行随机抽样。保留五字段完全相同行；窗口为北京时间 `[2017-11-25 00:00, 2017-12-04 00:00)`。购买用户与购买记录分别统计。

数据粒度是行为事件，没有订单号、金额或业务干预字段。更换数据源时需重新确认一行代表什么、用户与时间字段、缺失和重复规则、窗口及比较口径，不能直接套用本案例结论。

## 派生字段与失败规则

原始 CSV 和 `sample_events` 保持原样。临时视图新增 `behavior_type_clean = TRIM(behavior_type)`，只处理首尾空白，不转换大小写、不规范化用户 ID。所有行为合法性检查、购买人数、购买记录、加购路径、人群和品类指标统一使用 clean 字段。

检查范围是抽样表中的所有记录，包含时间窗外记录；这不是对未入样本的全量 CSV 做质量认证。缺失关键 ID、规范化后非法／缺失行为或无法解析的时间戳均导致失败。`prepare_data.py` 仅持久化原始样本，正式质量门槛在 `analysis.sql` / `run_analysis.py` 和 Notebook 中执行。

`quality_check.csv` 报告 `normalized_behavior_records` 和各问题数量，同一问题行可能命中多列，不能简单相加当作问题行数。有效窗外记录单独统计后排除；完全相同行按五个原始字段识别，继续保留。

新增导出均为聚合结果：`weekday_comparison.csv`、`after_only_history.csv`、`cart_to_buy_24h.csv`。中间用户—商品对不导出。比率通常以 0—1 保存，`buyer_rate_change_pp` 已是百分点。空分母保留空值，不填 0。
