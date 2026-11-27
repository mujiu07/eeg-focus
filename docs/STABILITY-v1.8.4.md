# v1.8.4 开发者模式稳定性测试

> 日期：2026-11-27
> 性质：本机工程稳定性测试；不代表真机、儿童、Windows 或长期使用验收。

## 1. 测试环境

- macOS；Python 3.9 `.venv`；FastAPI + Uvicorn；
- Microsoft Edge headless（Playwright Core）；1800×1020；deviceScaleFactor 1；
- 独立临时数据目录与端口 `8016`；`FOCUS_FROG_SESSION_TTL_SEC=900`；
- 信号源：手动模拟；不写入真实个人档案；
- 每轮打开 `game.html?test=manual&dev=1&sec=60`，保留同一页面跨导航复用；
- 计划 28 轮 × 约 65 秒。

## 2. 结果

| 指标 | 结果 |
|---|---|
| 实际轮数 | **28** |
| 实际覆盖时长 | **30 分 29 秒**（`13:20:43Z` → `13:51:12Z`） |
| 浏览器 FPS | 60–61，中位 61 |
| DOM 节点 | 734（全程不变） |
| JS 堆（used） | 2–4 MB，中位 3 MB |
| JS 堆（total） | 6–9 MB |
| 服务端 RSS | 159–164 MB，中位 163 MB；首 159，末 164 |
| Schema | 4 |
| SQLite Session 记录 | 0 → 27（每轮一局；测试数据目录） |
| SQLite round 记录 | 0（本轮测试只打开游戏并等待结束，没有点击产生逐轮记录；逐轮写入由 v1.8.4 Python 验收覆盖） |
| 监测连接样本 | 当前 `dev/current` 的 `monitor_clients` 为 0；`sessions` 只返回最近 5 个内存 Session，不能当作总 Session 数 |
| 页面脚本异常 | 无 `pageerror`；控制台仅有测试脚本故意访问不存在报告 `report.html?id=missing` 造成的 404（每轮一次，汇总保留最近 10 条） |

原始数据：

- `outputs/v1.8.4/stability.jsonl`
- `outputs/v1.8.4/stability-summary.json`

## 3. 解释

- 浏览器 FPS 稳定，DOM 节点没有随 28 次导航增长；JS used heap 在 2–4 MB 波动，没有单调增长。
- 服务端 RSS 从 159 MB 缓慢升到约 164 MB 后保持；这符合每轮写入报告、SQLite 页缓存和 Python 对象分配，不构成“已证明存在泄漏”。要证明无泄漏仍需更长、不同信号源、多浏览器与真机测试。
- 900 秒回收：测试使用真实 TTL 900 秒；30 分钟内已完成 Session 仍在宽限期，所以不能期待 RSS 立刻下降。TTL 回收逻辑由 v1.8.1 的单测覆盖（完成会话可释放内存、报告仍可读）；本次没有把“宽限期内仍驻留”解释成泄漏。
- `dev/current` 只返回最近 5 个 Session，故表中“内存 Session”固定为 5 不是总数；SQLite `sessions` 计数更适合观察写入。
- 404 是 test harness 在每轮结束后打开一个不存在的报告 ID 以离开游戏页，不是工作台或 API 请求失败；正式页面没有该导航。
- 手动模拟没有真实 EEG 波形，因此本测试主要覆盖页面/Session 生命周期、工作台 DOM 与资源趋势，不覆盖 Xmuse 去噪、真机断流或儿童可用性。

## 4. 结论

在本机 headless Edge + 手动模拟、28 轮/30 分钟的限定条件下，工作台页面保持 60–61 FPS、DOM 734、JS used heap 2–4 MB、服务端 RSS 159–164 MB；SQLite 按 Session 持续写入，未观察到浏览器脚本异常或 DOM 累积。该结果不能外推为真实硬件、儿童、Windows 或无资源泄漏的证明。
