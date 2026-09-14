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
