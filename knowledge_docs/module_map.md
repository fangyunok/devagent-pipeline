# 模块地图（示例产品线：分布式 KV / SQL 引擎）

| 模块 | 职责 | 关键接口 |  owner |
|---|---|---|---|
| kv_store | 带 TTL 的键值存储，写路径需审计 | put / get / delete | 存储组 |
| sql_parser | SQL 词法与 WHERE 条件解析 | parse_where | SQL 组 |
| txn_manager | 事务超时与提交协调 | begin / commit | 事务组 |

## 约定
- 新需求必须先归属到模块地图中的模块，未收录模块需在任务卡中留空并上报，禁止编造模块名。
- kv_store 所有写接口（put/delete）必须记录审计日志。
