# 沙箱执行镜像：运行生成代码与测试用例的最小 Python 环境。
# 由 DockerRunner 挂载脚本到 /app/run.py 执行，容器禁网 + 资源限额。
FROM python:3.11-slim

WORKDIR /app
# 无需额外依赖；runner 脚本自带结果序列化逻辑。
