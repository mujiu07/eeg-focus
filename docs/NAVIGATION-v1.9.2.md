# 专注小蛙 v1.9.2 页面导航与退出审计

> 审计日期：2026-11-28
> 范围：`web/` 下全部可直接访问页面与首页上的模态流程
> 原则：每个独立页面都有清晰首页入口；返回上一级、返回首页、结束游戏、切换档案是不同动作。

## 1. 导航关系图

```text
index.html（首页）
  ├─ 开始游戏 → 需要档案时 profiles.html?next=game
  │              → 需要/过期校准 calibrate.html
  │              → game.html?sec=N
  │                   ├─ 正常结束 → report.html?id=<session>
  │                   │                ├─ 再来一局 → game.html
  │                   │                └─ 首页 → index.html
  │                   ├─ 开发者退出 → dev.html
  │                   └─ 首页（确认）→ index.html
  ├─ 小蛙装扮（首页内模态）→ 关闭回 index.html
  ├─ 商城 / 签到 / 成就（首页内弹层）→ 关闭回 index.html
  ├─ 成长日记 → growth.html
  │                ├─ 家长报告 → parent.html
  │                └─ 首页 → index.html
  ├─ 家长报告 → parent.html
  │                ├─ 小蛙日记 → growth.html
  │                ├─ 历史详情 → history.html?id=<session>
  │                │                ├─ 家长报告（上一级）
  │                │                └─ 首页
  │                ├─ 设置 → settings.html
  │                └─ 开发者工作台 → dev.html
  ├─ 个人档案 → profiles.html
  │                ├─ 重新校准 → calibrate.html
  │                └─ 设置 → settings.html
  └─ 设置 → settings.html
                   ├─ 成长日记 / 家长报告 / 个人档案
                   └─ 开发者工作台 → dev.html
dev.html
  ├─ 无设备试玩 → game.html?demo=1&sec=60
  ├─ EDF 回放校准 → calibrate.html?test=replay
  ├─ 手动模拟校准 → calibrate.html?test=manual
  ├─ 实时工作台 → game.html?dev=1&sec=180
  ├─ 标准评估 → game.html?assessment=1&sec=90
  └─ 首页 → index.html
```

`calibrate.html` 与 `game.html` 的开发者/测试入口由 `dev.html` 的当前标签页 `sessionStorage` 授权；授权不会跨标签页传播。正式游戏、校准与评估都在进入时创建 Session，离开时按对应路径结束/清理。

## 2. 页面退出矩阵

| 页面 | 进入方式 | 返回首页 | 返回上一级/上下文 | 档案依赖 | 离开清理 |
|---|---|---|---|---|---|
| `index.html` | 根路径 | 当前页 | — | 无（开始游戏时要求） | 无长连接 |
| `profiles.html` | 首页/设置 | 顶部 `🏠 首页` | 设置；重新校准 | 当前档案高亮 | 无长连接 |
| `calibrate.html` | 首页/档案/开发者 | 顶部 `🏠 首页`（测试模式为开发者页） | 无独立上一级 | 正式校准要求当前档案 | `pagehide`/确认返回关闭 SSE，结束后台 Session |
| `game.html` | 首页/校准/开发者 | 顶部 `🏠 首页`，确认后返回 | 「退出游戏」回首页/开发者页 | 正式游戏要求当前档案 | `pagehide` 关闭游戏 SSE、监控 SSE、工作台、成就动画；未保存 Session 结束 |
| `report.html` | 游戏结束/历史 | 顶部 `🏠 首页`；底部「返回首页」为便利入口 | 底部开发者报告回开发者页 | 请求带当前档案；无档案时走旧式报告 | `pagehide` 停止曲线播放 |
| `growth.html` | 首页/家长 | 顶部 `🏠 首页` | 家长报告；设置 | 当前档案 | 无长连接 |
| `parent.html` | 首页/成长 | 顶部 `🏠 首页` | 小蛙日记；设置；开发者工作台 | 当前档案 | 无长连接；家长确认层是场景分隔 |
| `history.html` | 家长历史列表 | 顶部 `🏠 首页` | 家长报告；小蛙日记 | 当前档案归属由 API 校验 | 无长连接 |
| `settings.html` | 首页/档案/成长 | 顶部 `🏠 首页` | 档案；成长/家长；开发者 | 使用当前档案 | 无长连接 |
| `dev.html` | 设置/家长/旧 Konami | 顶部 `🏠 首页` | 底部「返回玩家模式」 | 无正式档案要求 | `pagehide` 关闭实时监视 SSE 并结束后台测试 Session |

首页弹层（装扮、商城、签到、成就）不是独立 URL；关闭弹层即回到首页，不需要重复设置“返回首页”按钮。首页的 `开始游戏` 只在英雄区保留一个主入口；`小蛙装扮` 只在功能导航保留一个入口。

## 3. 死链与错误跳转检查

- `tests/selfcheck_v192_ui_static.js` 扫描全部 `web/*.html` 的本地 `href`；除 `data:` favicon、锚点和动态导出链接外，所有目标页面均存在。
- 不存在的页面：0。
- 首页重复主入口：0（开始游戏、装扮、设置、校准各有唯一主导航位置）。
- 独立页面缺少首页入口：0。
- 离开正式游戏/校准/评估时无确认或清理：0。
- `report.html` 底部首页是长报告的可达性辅助，不替代顶部全站首页规范；开发者报告保留回开发者页的上下文动作。
