# ffp-rag —— 常旅客 RAG

常旅客（里程/积分/信用卡/酒店）领域的检索增强问答系统。后端为 FastAPI + Chroma
向量库，多个前端（网页 React、微信小程序、未来 iOS）共享同一套无状态 HTTP API。

## Language

**常旅客 / FFP**：
Frequent Flyer Program。本项目的领域范畴：航司里程与会籍权益、信用卡积分转点、酒店积分互通。

**域 / domain**：
一条知识片段所属的领域分类，取值 `airline` / `credit_card` / `hotel` / `personal_account` / `other`。
_Avoid_: 分类、category

**片段 / Fragment**：
入库到向量库的最小知识单位，含 `domain`、`source`、`text`、`url`。检索与引用都以片段为单位。
_Avoid_: chunk、文档、段落

**来源 / Source**：
一条回答所引用片段的出处标签（`domain` + `source` + 相似度 `score`）。前端展示以建立可信度。
_Avoid_: 引用、reference、出处链接

**追问改写 / Query Rewrite**：
把依赖上下文的追问（如「那金卡呢」）结合历史改写成独立完整、可直接检索的问题。
_Avoid_: 补全、问题扩展

**会话 / Conversation**：
一轮多轮对话的完整消息序列（`messages`，每条含 `role` 与 `content`）。会话历史由前端
每次请求携带（问答本身无服务端会话状态）；但用户身份与每日额度是服务端状态（见「登录态」）。
_Avoid_: session、聊天记录、上下文

**登录态 / Auth**：
小程序 `wx.login` 拿 code，后端 `code2session` 换 openid 并签发 token；`/chat` 系列
须带 `Authorization: Bearer <token>`，按 openid 限每日额度。管理接口另用 `ADMIN_TOKEN`。
_Avoid_: 鉴权、session、账号

**问题模板 / Question Template**：
一组预先定义的规范问法，既是冷启动的示例问题，也是热门榜的统计与展示单位。
用户的每次真实提问会用 embedding 归到相似度最近的模板上。
_Avoid_: 预设问题、示例、FAQ

**热门榜 / Popular Questions**：
按累计命中次数排序的问题模板列表，供前端首屏空状态展示。冷启动（计数为空）时
回退到模板的预设顺序。
_Avoid_: 排行榜、热搜、推荐问题

**规范化 URL / Canonical URL**：
把同一篇文章的各种链接变体（追踪参数、`#` 片段、大小写差异）折叠成唯一形式后的 URL。
判断「是否已录入」以规范化 URL 为准。公众号 `mp.weixin.qq.com` 仅保留 `__biz/mid/idx/sn`。
_Avoid_: 原始链接、去重 key、URL 指纹

**已录入 / Ingested**：
一篇文章的规范化 URL 已有片段真正写入向量库（`ingest-parsed` 成功）。
仅「解析过但未入库」不算已录入，可重新解析。判定以向量库中是否存在该 URL 的片段为准。
_Avoid_: 已解析、已抓取、已处理

**用户档案 / User Profile**（见 ADR-0003）：
用户在小程序「我的」页维护的个人常旅客资产，含三类**条目 / Entry**：航司会籍、
酒店会籍、信用卡。仅存前端 `Storage`，后端不参与。每条只记相对稳定的信息
（品牌 + 等级/卡种 + 可选标识号），**不含里程/积分余额**。
_Avoid_: 账户、user account、会员数据（`personal_account` 是知识库的域取值，与此无关）

**纠错记录 / Correction**（见 ADR-0005）：
用户对某条 AI 回答的报错，含当时的问答快照与命中的**知识条目 id**。它是给管理员的
待办项，不自动改库；管理员据此修正知识后手动标记已处理。用户侧的动作叫「报错」，
后台那一屏叫「纠错队列」。
_Avoid_: 错题本、反馈、feedback、bug（「知识条目」无关联时表示库里缺这条知识）

**会籍 / Membership**：
用户档案中「航司」或「酒店」类条目，含所属品牌与**等级 / Tier**（如 万豪钛金、
国航白金）。等级取自内置「品牌 → 等级清单」预置表。
_Avoid_: 等级卡、身份、status（中文统一用「会籍/等级」）

