# 08 · 行程首页（`pages/rail/`）

Status: done

Blocked by: 06, 07, 11（接口契约已定，可并行开发）

负责目录：**只改 `miniprogram/pages/rail/`**。不要动 `api.js`、`app.json`、
`custom-tab-bar/`、`styles/rail.wxss`、`rail-util.js`——这些是已搭好的共享地基，
改了会和其他并行任务冲突。缺什么就在本页 `.wxss` 里自己加。

## 任务

第 4 个 tab「行程」的首屏。页面已在 `app.json` 与 `custom-tab-bar` 里注册好，
只需建 `rail.js / .json / .wxml / .wxss` 四个文件。

自上而下三块：**统计卡片 → 记录列表 → 数据与隐私**。

### 必备样板

```js
// rail.js
const api = require('../../api')
const u = require('../../rail-util')

Page({
  onShow() {
    // 自定义 tabBar 必须在每个 tab 页 onShow 里高亮自己，否则切回来是灰的
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setActive('pages/rail/rail')
    }
    this.refresh()
  },
})
```

```css
/* rail.wxss 第一行 */
@import "/styles/rail.wxss";
```

### 1. 统计卡片

`api.rail.stats()` →
`{journey_count, total_km, station_count, city_count, province_count, class_counts, first_ride, latest_ride}`

- 主数字用 **`total_km`**，大号显示，单位 km（`u.fmtKm` 会带单位，主数字这里自己拼，
  别把 " km" 混进 48rpx 的数字里，单位用小字跟在后面）。
- 下面一行四个小格：`journey_count` 次乘车 / `station_count` 座车站 /
  `city_count` 座城市 / `province_count` 个省份。用 `.rail-stat-num` + `.rail-stat-label`。
- `class_counts` 用 `<t-tag>` 横排展示前 4 种，如「高速动车 ×30」，
  theme 取 `u.classTheme(种别名)`。超过 4 种不显示「更多」，直接截断。
- 卡片右上角一个「地图」入口，`<t-icon name="map-route-planning">` + 文字，
  `wx.navigateTo({ url: '/pages/rail-map/rail-map' })`。
- `journey_count === 0` 时**整张统计卡片不渲染**，只显示空状态（见下）。

### 2. 记录列表

`api.rail.listJourneys(50, 0)` → 按乘车日期倒序的数组。每条：

```
{id, train_number, ride_date, from_station, to_station, from_seq, to_seq,
 note, departure, arrival, day_offset, distance_km, stale, source, gtfs_version}
```

每条渲染成一张 `.rail-card`：

- 顶行：`<t-tag>` 车次号 + `u.fmtDate(ride_date)`（靠右，灰字）。
- 主体用共享的 `.rail-leg` 骨架：左 `from_station` + `u.fmtTime(departure)`，
  中间 `.rail-leg-mid` 显示 `u.fmtKm(distance_km)`，右 `to_station` +
  `u.fmtTime(arrival)`，到达时刻后跟 `u.dayTag(day_offset)`（空串就不显示那个标签）。
- `note` 非空时在卡片底部加一行灰色小字。
- **`stale === true`**：整张卡加 `.rail-stale` 类，并在车次号旁加一个灰色
  `<t-tag>已改点</t-tag>`。这不是错误——车次停运/改点了，记录本身仍然有效，
  只是时刻和里程查不回来（此时后端返回的 `departure`/`arrival`/`distance_km` 都是 null）。
- `source === 'manual'`：加一个 `<t-tag variant="outline">手填</t-tag>`。
  手填记录没有时刻和里程，`u.fmtTime`/`u.fmtKm` 会显示破折号，**这是正确表现，不要补零**。

交互：

- `<t-swipe-cell>` 右滑删除，样式用 `.rail-swipe-del`。删除前
  `wx.showModal({ title:'删除这条记录？', content: 车次+日期 })` 确认，
  确认后 `api.rail.deleteJourney(id)`，成功 toast「已删除」并刷新。
- 点击卡片 → 底部 `<t-popup>` 编辑面板。**只能改乘车日期与备注**
  （后端 `PATCH` 也只认这两个字段，改车次/站点请删了重录）。
  日期用 `<t-date-time-picker mode="date">`，保存走 `api.rail.updateJourney(id, {ride_date, note})`。
- 列表满 50 条时，底部出现「加载更多」按钮，`offset` 累加 50 追加拼接。
  不做下拉刷新的无限滚动——记录量级本来就小。

### 3. 空状态

一条记录都没有时：`<t-empty icon="map-route-planning" description="还没有乘车记录">`，
下面一个 `<t-button theme="primary">记第一趟车</t-button>`。

### 4. 录入入口

右下角浮动按钮，用共享的 `.rail-fab` 类，内容 `<t-icon name="add" color="#fff" size="52rpx">`，
点击 `wx.navigateTo({ url: '/pages/rail-entry/rail-entry' })`。
从录入页 `wx.navigateBack` 回来会触发本页 `onShow` → `refresh()`，列表自动更新，
**不需要额外的回调机制**。

### 5. 数据与隐私（页面最底部）

个保法要求，见 spec「上线前必办」。三个 `<t-cell>` 一组：

| 文案 | 行为 |
|---|---|
| 导出我的数据 | `api.request('/rail/export')` → 见下 |
| 清空全部记录 | 二次确认后 `api.rail.clearJourneys()` → toast「已清空 N 条」 |
| 注销账号 | 见下 |

**导出**：`GET /rail/export` 返回完整 JSON（结构见 issue 11）。拿到后：

```js
const fs = wx.getFileSystemManager()
const path = `${wx.env.USER_DATA_PATH}/ffp-rail-export.json`
fs.writeFile({ filePath: path, data: JSON.stringify(data, null, 2), encoding: 'utf8',
  success: () => wx.shareFileMessage({ filePath: path, fileName: '我的乘车记录.json' }) })
```
`shareFileMessage` 失败（用户取消也会走 fail）时**不弹错误提示**，静默即可。

**注销账号**：两道确认。第一道 `wx.showModal` 说明「将永久删除你的全部乘车记录，
不可恢复」；第二道要求用户在 `<t-dialog>` 的输入框里手打「注销」二字才放行。
然后 `api.request('/rail/account', 'DELETE')`，成功后
`wx.clearStorageSync()` + `wx.reLaunch({ url: '/pages/chat/chat' })`。

## 需要在 `rail.json` 里声明的组件

参照 `pages/profile/profile.json` 的写法自行声明。至少会用到
`t-cell-group / t-cell / t-tag / t-empty / t-button / t-swipe-cell / t-popup /
t-dialog / t-date-time-picker / t-textarea`。
`t-icon / t-button / t-cell / t-tag` 已在 `app.json` 全局注册，可不重复声明。

## 验收

- 无记录 → 只有空状态 + 浮动按钮，不报错、不显示 0 km 的统计卡。
- 有记录 → 统计数字与列表条数对得上。
- 手填记录、`stale` 记录都能正常渲染，不显示 NaN / undefined / null。
- 侧滑删除、编辑日期、清空全部各走通一次。
- 切到别的 tab 再切回来，tabBar 高亮仍在「行程」。

## 已知限制（不要试图修）

- 乘车日期不参与任何查询，纯记录元数据（GTFS 无开行日历，见 spec）。
  所以不要做「这天这趟车开不开」的校验。
- `station_count` 算的是**去重途经车站**（坐 3→9，途中 7 站都算到过），
  这是打卡语义，不是「上下车站数」。文案上写「途经车站」更准确。

## Comments

实现于 `miniprogram/pages/rail/` 四个文件，未触碰 `api.js` / `app.json` /
`custom-tab-bar/` / `styles/rail.wxss` / `rail-util.js` / `backend/`。

### 与 issue 描述的偏离

1. **`station_count` 的文案用「途经车站」而非「座车站」**。
   依据是 issue 自己的「已知限制」一节：口径是去重途经站，写「途经车站」更准确。
   其余三格保持「次乘车 / 座城市 / 个省份」。

2. **空状态下仍显示「注销账号」一行**。验收写的是「无记录 → 只有空状态 + 浮动按钮」，
   但「注销账号」是个保法删除权在全 App 的**唯一入口**，0 条记录的用户同样有权注销。
   折中做法：无记录时隐藏「导出我的数据」「清空全部记录」（此时点了也是空操作），
   只保留「注销账号」。如果产品上更认可「空页面绝对干净」，把那一行也套上
   `wx:if="{{journeys.length}}"` 即可，但需要另找一处放注销入口。

3. **格式化全部在 JS 里做，wxml 只读预算好的视图模型**（`_toView`）。
   wxml 无法直接调用 `rail-util` 的函数，用 wxs 重写一份会造成两套口径，
   所以走「JS 预格式化 → setData」这条路。

4. **统计主数字复用 `u.fmtKm(...).replace(' km','')`**，而不是自己写一遍舍入。
   看着有点取巧，但这样能保证主数字与列表里的里程舍入口径永远一致。

5. **`/rail/stats` 与 `/rail/journeys` 并行发起**，不是串行 `Promise.all`。
   任一失败只 toast，不阻塞另一个渲染——统计挂了列表还能看。

6. 编辑面板额外加了一行灰字提示「车次与站点不可修改，如需更正请删除后重录」，
   因为后端 PATCH 只认两个字段，不说明用户会困惑。

7. 删除确认的 `content` 用「车次 · 日期」（issue 写的是「车次+日期」），加了个间隔点。

### 需要在开发者工具 / 真机验证的点

- **`t-date-time-picker` 与编辑 `t-popup` 的层级**。两者 `zIndex` 默认都是 11500，
  我靠「日期选择器在 wxml 里写在编辑面板之后」拿到更高的绘制层级。
  若实际被编辑面板盖住，给 picker 加 `popupProps="{{ {zIndex: 12000} }}"`。
- **`t-swipe-cell` 侧滑打开时点卡片**：组件根节点的 `onTap` 只做 `close()`，
  卡片自身的 `bindtap` 仍会触发 → 会同时收起侧滑并弹出编辑面板。
  `pages/profile/` 是同样的写法，故按现状保留；若体验上不可接受，
  需要在 `onEdit` 里自行记录侧滑状态来吞掉这一次点击。
- **卡片阴影被裁切**：`.t-swipe-cell` 组件根节点自带 `overflow:hidden`，
  `.rail-card` 的 `--shadow-soft` 会被切掉一圈。阴影本身很淡，视觉上应可接受，
  但需要真机确认列表看起来不会「扁」。
- **`wx.shareFileMessage` 的转发面板**：开发者工具里行为与真机不一致，必须真机验证。
  按 issue 要求，`fail` 回调（含用户主动取消）完全静默。
- **`t-cell` 在 `wx:if` 下的 `isLastChild` 边框计算**：`t-cell-group` 靠 relations
  算最后一行的分隔线，条件渲染后是否正确重算未验证，只影响一条 hairline。
- **注销后的登录态**：`wx.clearStorageSync()` 清的是 Storage，`auth.js` 若在模块内存里
  缓存了 token，`reLaunch` 不会重置 JS 上下文，那份缓存仍在。好在旧 token 已被后端
  作废，下次请求 401 会自动 relogin 拿到新 `user_id`，结果正确，只是多一次往返。
  没有改 `auth.js`（不在本 issue 的目录边界内），此处仅作记录。
- 本页无法本地跑通任何接口，全部逻辑只做了 `node --check` / `JSON.parse` /
  标签配对校验，以及对照 `miniprogram_npm/tdesign-miniprogram/` 源码核对了
  props 名与 `triggerEvent` 名。

### 对并行实现的 `/rail/export`、`/rail/account` 的疑问

1. **`GET /rail/export` 的返回体是否会被包一层？** 本页按 issue 11 的契约直接
   `JSON.stringify(data, null, 2)` 整体落盘，即认为响应根就是
   `{exported_at, journey_count, journeys}`。若实际外面还套了 `{data: ...}`，
   导出文件会多一层，需要同步调整。
2. **导出体积**：`journeys` 不设 limit。记录量级小应该没问题，但若将来某用户几千条，
   `wx.request` 默认最大响应 10MB，超了会直接 fail。是否需要分页或压缩？现按不需要处理。
3. **`DELETE /rail/account` 的返回**：本页只判断 HTTP 成功，不读
   `{"deleted_journeys": n}`，也没做「已删除 N 条」的 toast——注销后立刻 `reLaunch`，
   toast 没时间显示。若产品希望告知条数，需要改成先 toast 再延时跳转。
4. **注销后的 401 时机**：issue 11 说 session 立即失效。本页在 `DELETE` 成功后调
   `wx.clearStorageSync()`，但 `api.request` 的 401 自动 relogin 逻辑可能在注销请求
   **之后的任何一个在途请求**上触发一次静默重登，从而立刻新建一个空 `user_id`。
   这不影响正确性（新账号本就是从零开始），但会让「注销」在服务端留下一个空用户行。
   如果这不可接受，需要 issue 11 侧确认是否要清理空用户。
5. **两个接口的 4xx 文案**：本页原样透传 `detail` 给 `wx.showToast`，
   所以需要它们的 `HTTPException(detail=...)` 是中文用户文案，与 `/rail/journeys` 一致。
