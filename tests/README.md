# 产品集成测试

根 tests 只管理跨模块与产品流程：

- integration：canonical 数据层、backend、TypeScript staging 之间的契约、范围、分页、重算、只读与来源归档。
- e2e：从仓库外运行 CLI，核对导入、报告、API 会话和证据，以及评价不改变报告；这是服务流程验收，尚不包含原生 App UI。

共享夹具在 `tests/conftest.py`：仓库根与 backend 合成数据写入器的 `sys.path`、`synthetic`、`gateway_harness`（临时 HOME、禁网、禁子进程的真实 Gateway）；辅助函数在 `tests/integration/gateway_support.py`。依赖真实心跳的网关用例标 `serial`。

`pnpm check:integration` 自动构建 staging producer。没有构建产物时测试失败，防止漏掉桥接验收。

模块内部测试分别在 packages/backend/tests、packages/data/tests 和 packages/connectors/tests；原型行为在 prototypes/advance/tests。不要把真实历史、派生数据库或截图产物加入测试资源。
