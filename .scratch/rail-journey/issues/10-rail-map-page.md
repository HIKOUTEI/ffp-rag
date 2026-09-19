# 10 · 打卡地图（`pages/rail-map/`）

Status: done

Blocked by: 11（`GET /rail/map` 接口，契约已在下方定死，可并行开发）

负责目录：**只改 `miniprogram/pages/rail-map/`**。不要动 `api.js`、`app.json`、
`custom-tab-bar/`、`styles/rail.wxss`、`rail-util.js`。

## 任务

把用户坐过的所有区段画在地图上，形成一张属于他自己的铁路版图。
从行程页统计卡片的「地图」入口 `wx.navigateTo` 进入。
建 `rail-map.js / .json / .wxml / .wxss`。

## 数据来源：`GET /rail/map`

**一次请求拿全部**，不要按车次逐个调 `/rail/trains/{number}`——那会打爆日额度也很慢。

```js
api.request('/rail/map')
```

响应（由 issue 11 实现，契约如下，照着写即可）：

```json
{
  "legs": [
    { "journey_id": "a1b2", "train_number": "G1", "ride_date": "2026-09-14",
      "points": [ {"station": "北京南", "lat": 39.86, "lon": 116.38}, … ] }
  ],
  "stations": [ {"name": "北京南", "lat": 39.86, "lon": 116.38, "count": 3} ],
  "bounds": {"min_lat": 22.5, "min_lon": 103.1, "max_lat": 45.8, "max_lon": 126.6}
}
```

- `points` 是该条记录**上车站到下车站之间的全部途经站**，按 seq 升序，
  可直接当 polyline 的点序列。
- **坐标已是 GCJ-02**，微信 `<map>` 用的就是 GCJ-02，直接塞进去，
  **不要再做任何坐标转换**。（后端 `app/rail/geo.py` 已经转过了。）
- `stations` 是去重后的所有到过的车站，`count` 是到过几次。
- 手填记录不出现在 `legs` 里（没有停站表，画不出线）；
  若其起讫站名能匹配到库里的车站，则会出现在 `stations` 里。
- 一条记录都没有时 `legs`/`stations` 为空数组，`bounds` 为 `null`。

## 渲染

```xml
<map id="railmap" longitude="{{center.lon}}" latitude="{{center.lat}}"
     scale="{{scale}}" polyline="{{polyline}}" markers="{{markers}}"
     show-location="{{false}}" enable-rotate="{{false}}" style="width:100%;height:100vh;" />
```

- **polyline**：每条 leg 一段，`{ points: [{latitude, longitude}…], color: '#0a84ffcc',
  width: 4, arrowLine: false }`。注意微信要的字段名是 `latitude`/`longitude`，
  接口给的是 `lat`/`lon`，需要映射。
- **markers**：每个 station 一个，`{ id, latitude, longitude, width: 16, height: 16,
  iconPath: '/pages/rail-map/dot.png', callout: {...} }`。
  ⚠️ 不要引入图片资源——**用 `<cover-view>` 做不了标记点**，
  改用微信 marker 的内置样式：省掉 `iconPath`，只给 `callout`
  （`{content: 站名, display: 'BYCLICK', bgColor: '#fff', padding: 8, borderRadius: 8}`），
  微信会用默认红色气泡针。站多的时候（>200）**只渲染 count ≥ 2 的站**，
  避免 marker 过密卡顿；并在右上角提示「已隐藏只到过一次的车站」。
- **初始视野**：拿到数据后调
  `wx.createMapContext('railmap', this).includePoints({ points: 全部点, padding: [60,40,60,40] })`，
  比自己算 scale 靠谱。`bounds` 为 null（无数据）时退化为中心
  `{lat: 35.0, lon: 105.0}`、`scale: 4`（全国视野）。

## 顶部信息条

浮在地图上方的一张半透明卡片（`position: fixed; top: 24rpx`），显示
「N 条线路 · M 座车站」，右侧一个关闭按钮 `wx.navigateBack()`。
数据直接从响应里数：`legs.length` / `stations.length`。

## 空状态

`legs` 与 `stations` 都为空时，不渲染地图，显示
`<t-empty icon="map-route-planning" description="还没有可以画在地图上的行程">`
+ 一行小字「手填的记录没有停站信息，画不出线路」+ 一个「去记一趟车」按钮
（`wx.redirectTo({url: '/pages/rail-entry/rail-entry'})`）。

## 明确不做

- **不做真实铁路线形**。数据源 GTFS 没有 `shapes.txt`，只能车站点直连。
  画出来的线是折线不是铁轨走向，这是已知且接受的（spec「明确不做」第一条）。
  不要试图引第三方线形数据或做曲线插值。
- 不做点击线路查看详情、不做按年份筛选、不做热力图。第一版只画出来。

## 验收

- 有 3 条以上记录时，线路能画出来且视野自动框住全部点。
- 全是手填记录时 → 地图上只有点、没有线，信息条里说明「手填的记录没有停站信息，
  画不出线路」。（**修正 2026-09-17**：本条原写「→ 空状态」，与「渲染」一节矛盾。
  手填记录的站名若能匹配到库里是会进 `stations` 的，走空状态等于把用户到过的站藏起来。
  以「渲染」一节为准：只有 `legs` 与 `stations` **都**为空才走空状态。）
- 一条记录都没有时 → 空状态。
- 中老铁路那种跨境车次（万象、琅勃拉邦）不会让视野崩掉——`includePoints` 自己会处理。

## 需要在 `rail-map.json` 里声明的组件

`t-empty` 等按需声明。`<map>` 是小程序原生组件，不需要声明。
注意原生组件层级最高，**顶部信息条要用 `<cover-view>` 才能盖在地图上**。

## Comments

实现于 `miniprogram/pages/rail-map/` 四个文件，未触碰目录外任何文件。
`rail-map.json` 只声明了 `t-empty` 与 `t-button`。

### 与 issue 描述的偏离

1. **空状态判定放宽为「`legs` 与 `stations` 都为空」，与「渲染」一节一致，
   但和「验收」第二条冲突。** 验收写「全是手填记录时 → 空状态」，可按 issue 11 的契约，
   手填记录的起讫站只要能匹配到库里车站就会进 `stations`。若此时走空状态，
   等于把用户实实在在到过的几十个站藏起来，明显更差。
   现在的行为是：`legs` 为空但 `stations` 不为空 → 正常渲染地图（只有点、没有线），
   并在顶部信息条里补一行小字「手填的记录没有停站信息，画不出线路」。
   这满足验收的真实意图（「不是白屏、不是空白地图」），但与字面不符，**需要确认**。
   两个站名都匹配不上时 `stations` 也为空，仍然走空状态。

2. **`includePoints` 优先只喂 `bounds` 的两个对角点，而不是「全部点」。**
   两者框出的矩形完全一致，但一个 50 条记录的用户全部途经站可能上千个点，
   全喂进去纯属浪费 setData 序列化。`bounds` 为 null 时才退化为收集全部点。

3. **`includePoints` 调两次**（setData 回调里一次 + 300ms 后补一次）。
   真机上 `<map>` 偶有还没布局完就收到 includePoints 而静默失效的情况，
   同一组点重复调不会产生视觉跳动。若真机验证下来一次就稳，可以删掉那个 setTimeout。

4. **callout 内容加了次数**：到过 ≥2 次的站显示「北京南 · 3 次」，1 次的只显示站名。
   issue 只写了「站名」，但 `count` 已经在手上，白扔可惜。

5. **多了加载中 / 加载失败两态**。issue 没提，但 `/rail/map` 是网络请求，
   不做就是白屏。失败态给了「重试」按钮。

6. **关闭按钮做了无上一页的兜底**：`wx.navigateBack` 的 `fail` 回调走
   `wx.switchTab('/pages/rail/rail')`。正常路径（从行程页 navigateTo 进来）用不到。

7. **marker 的 `iconPath` 按 issue 要求省掉了**，用微信内置默认针；
   `width: 16 / height: 16` 仍按 issue 保留，但没有 `iconPath` 时这两个值是否生效存疑。
   整页不含任何图片资源文件。

8. 顶部信息条的关闭按钮用了字符 `✕` 而不是 `t-icon`——`cover-view` 里只能放
   `cover-view` / `cover-image` / `button`，自定义组件放不进去。

### 对 `/rail/map` 契约的疑问

- **`stations[].count` 在没有 leg 的手填记录里怎么算？** issue 11 写的是「`from_station` /
  `to_station` 各 +1」，也就是手填记录只计两端。而时刻表记录计的是全部途经站。
  两种口径混在同一个 `count` 里，callout 上的「N 次」语义就不齐。
  前端按现状原样显示，不做加工。
- **`stations` 有没有条数上限？** 前端按 >200 站做了抽稀（只画 count ≥ 2）。
  若后端已经排序（比如按 count 降序），前端可以改成「取前 N 个」，会更可控。
  现在的实现不依赖任何排序。
- **`points` 里会不会出现 `lat`/`lon` 为 null 的站？**（库里坐标缺失）
  目前前端不过滤 null，会直接塞进 polyline，微信的行为未知。
  如果后端不能保证非空，希望在接口侧就把这类点剔掉，或者明确告知由前端过滤。
- **`bounds` 是不是已经是 GCJ-02？** 契约没写。前端拿它算中心点和 `includePoints`，
  如果 `bounds` 是 WGS84 而 `points` 是 GCJ-02，视野会整体偏 550 米。
  按「坐标已是 GCJ-02」的措辞理解为 bounds 也转过了，**需要后端确认**。

### 必须在开发者工具 / 真机里人工验证的点

地图这块静态检查一点都查不出来，以下全部要手动看：

1. **`<cover-view>` 是否真的盖在地图上。** 这是本页最容易翻车的地方。
   要确认顶部信息条没有被地图吞掉、文字不是空白方块、点「✕」能退回行程页。
   开发者工具对原生组件是模拟渲染，**工具里正常不代表真机正常，必须真机各看一遍**。
2. **`cover-view` 的样式是否成立。** cover-view 只支持很有限的 CSS：
   不支持 box-shadow / 渐变 / backdrop-filter / transform。现在半透明只靠
   `background-color: rgba(255,255,255,0.92)`，要看清楚在深色地图底（如卫星区、水域）
   上文字对比度够不够。另外 `flex` 简写在部分基础库不生效，已全部写成
   `flex-grow / flex-shrink / flex-basis` 长属性，仍需确认横向布局没塌。
3. **`includePoints` 的实际效果。** 已知平台差异：
   - **开发者工具直接忽略 `padding` 参数**，所以工具里边距不对是正常的；
   - **安卓只认 `padding` 数组的第一项**（四边同值）。
   要在 iOS 与安卓真机各看一次留白是否合理，必要时把 padding 改成四个相同的值。
4. **300ms 补调是否必要 / 是否够。** 低端安卓机上如果第一次 fit 之后视野仍不对，
   说明 300ms 不够；反之如果一次就稳，可以删掉。
5. **省掉 `iconPath` 的 marker 在两端长什么样。** 社区反馈 iOS 某些基础库版本会在
   默认针上再叠一个小灰点。要确认默认针的尺寸/颜色可接受，不可接受就得引一张
   透明或纯色小图（那会破坏「不引入图片资源」的约束，需要先讨论）。
6. **callout `display: 'BYCLICK'` 的点击行为。** 点针要弹出站名气泡，再点别处要收起；
   气泡的 `bgColor` / `padding` / `borderRadius` 在两端渲染是否一致。
7. **性能。** 造一个上百条记录的账号（`legs` 上百段、`points` 上万个点），
   看首帧耗时与拖动/缩放是否掉帧。>200 站的抽稀分支和右上角「已隐藏只到过一次的车站」
   提示只有这种数据量下才会出现，**必须造数据才能验证到**。
8. **跨境车次。** 中老铁路（万象、琅勃拉邦）这类记录进来后，
   视野是否被 `includePoints` 正确框住、境外段坐标（GCJ-02 在境外不定义，
   后端 `geo.out_of_china` 会原样返回 WGS84）画出来有没有明显错位。
   **这一条很可能会看到境内境外接缝处有几百米的折角，属于已知取舍，要确认可接受。**
9. **`height: 100vh`** 在带原生导航栏的页面、以及有安全区的机型（刘海屏 / 底部横条）上
   是否正好一屏、会不会出现多余滚动。
10. **空状态**：清空全部记录后进本页，应看到 `map-route-planning` 图标 +
    「还没有可以画在地图上的行程」+ 小字 + 「去记一趟车」按钮，点按钮 `redirectTo`
    到录入页且不能再返回到空地图。
11. **加载失败态**：断网进本页，应看到错误文案 + 「重试」按钮，恢复网络后点重试能加载出来。
