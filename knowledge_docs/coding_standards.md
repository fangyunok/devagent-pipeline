# 编码规范（评审门禁依据）

## SEC-01 禁止硬编码口令
任何 password/secret 不得字面量写入代码，统一走配置中心。违反记 major。

## SEC-02 禁止动态执行
禁止使用 eval/exec 执行外部输入。违反记 critical，直接拦截 MR。

## REL-01 TTL 边界语义
ttl <= 0 表示立即过期，不得视为永不过期；读取路径发现过期键必须惰性删除。

## OBS-01 写操作审计
写操作必须调用 audit_log(action, key)，需求中的「留痕」「审计」「日志」同义。
缺少审计记 major。

## ERR-01 异常处理
禁止裸 except，必须捕获具体异常类型。违反记 minor。
