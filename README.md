# 儿童产品风险召回

本项目服务于儿童用品风险与召回。认证、检测、批次流向、消费者反馈和分级召回需要协同。
系统支持清晰的领域对象、事件记录和责任追溯，运行入口提供稳定的健康检查，便于本地联调和运维巡检。

## 运行

```bash
python3 service.py --check          # 基础配置检查
python3 service.py --port 8000      # 启动服务，/health 确认服务身份
python3 service.py --seed --port 8000  # 载入演示数据（登记→销售→召回全链路）
npm test                            # 运行全部测试（契约 + 领域 + 接口）
```

## 领域对象

- **登记**：型号（Model）、批次（Batch）、固件（Firmware，含功能开关与付费规则）、设备（Device，按序列号）。
- **检测结论**（Assessment）：按（型号, 固件版本）范围发布；结论变化生成新版本并记录替代关系，旧版本保留可溯。
- **家长同意**（Consent）：按设备与能力范围记录，同一范围取最新一条为当前状态。
- **流向**（FlowEvent）：入库、跨店调拨、销售、离线盘点、退回逐条记录；调拨校验当前门店，流向不断链；离线盘点保留原始盘点时间与上传时间。
- **处置动作**（RecallAction）：分阶段停售（stop_sale）、远程关闭（remote_disable）、召回（recall），按型号 + 批次 + 固件版本圈定范围，阶段含截止时间。
- **通知**（Notice）：发布后修订生成新版本，旧版本内容不被覆盖。
- **证据**（Evidence）：退款、换货、拒绝升级由门店登记；超期未处理由扫描生成（幂等）。
- **事件日志**：每次状态变化追加一条事件，支撑责任还原。

## 关键不变量

- 基础通话、紧急求助、必要定位为基础能力：开关关闭、远程关闭、其他功能停用都不会使其失效；针对基础能力的远程关闭请求会被拒绝。
- 高风险能力按年龄与场景逐步开放：未达适龄门槛、场景受限、缺家长同意时逐项给出阻断原因。
- 停售中的设备禁止销售登记；召回为每台受影响设备生成处置任务，退款/换货/拒绝升级/超期均留证据。

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查 |
| POST | `/models` `/batches` `/firmwares` `/devices` | 登记型号、批次、固件（功能开关 + 付费规则）、设备 |
| POST | `/assessments` | 发布检测结论（自动版本递增） |
| GET | `/assessments?model_id=&firmware_version=` | 结论版本历史 |
| POST | `/consents` | 登记/撤回家长同意 |
| POST | `/flow` | 流向事件（register/transfer/sale/stocktake/return/recall_return） |
| GET | `/devices/{serial}/flow` | 单台设备完整流向 |
| GET | `/devices/{serial}/features?age=&scenario=` | 能力可用性评估 |
| POST | `/actions` | 发起分阶段处置 |
| GET | `/actions/{id}` | 处置详情（任务、通知、证据） |
| POST | `/actions/{id}/notices` | 发布通知（v1） |
| POST | `/notices/{id}/revisions` | 修订通知（新版本，旧版保留） |
| GET | `/notices/{id}` | 通知全部版本 |
| POST | `/evidence` | 登记退款/换货/拒绝升级证据 |
| POST | `/actions/{id}/scan-overdue` | 扫描超期未处理并生成证据 |
| GET | `/trace/{serial}?role=regulator\|enterprise\|store` | 序列号追溯（按角色脱敏） |
| GET | `/events` | 事件日志 |

## 角色视图

- **regulator（监管）**：从一个序列号还原认证（检测机构）、销售（门店）与处置（动作发起人、证据登记人）责任，家庭信息全量可见。
- **enterprise / store（企业与门店）**：仅见完成召回所必需的家庭信息——姓氏脱敏、电话脱敏、保留城市与儿童年龄，详细地址不可见。

示例：

```bash
curl -s "http://127.0.0.1:8000/trace/SN-DEMO-0001?role=store"
# {"device": {"family": {"guardian_name": "张*", "phone": "138****5678", ...}}, ...}
```
