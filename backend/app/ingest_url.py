"""URL 摄入管线：抓取网页 + AI 抽取切分打标。小红书不支持（反爬）。"""
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

from app import config
from app.rag import client
from app.urlutil import canonical_url

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def fetch(url: str):
    """抓取网页，返回 (title, plain_text)。抓不到则抛 ValueError。"""
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        raise ValueError(
            "小红书有强反爬，服务器无法直接抓取。请改用『粘贴文本』方式（后续版本）或换其他来源。")
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"抓取失败：{e}")
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")
    # 标题：优先 og:title（公众号 <title> 常为空，真实标题在此），退回 <title>
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()
    if not title and soup.title:
        title = soup.title.get_text(strip=True)
    if not title:
        title = url
    # 发布日期：公众号 HTML 里的 create_time: '2026-06-12 14:10'，取日期部分
    date = ""
    m = re.search(r"create_time:\s*'(\d{4}-\d{2}-\d{2})", resp.text)
    if not m:  # 退回：页面里第一个 YYYY-MM-DD
        m = re.search(r"(20\d{2}-\d{1,2}-\d{1,2})", resp.text)
    if m:
        date = m.group(1)
    # 微信公众号正文常在 #js_content
    node = soup.select_one("#js_content") or soup.body or soup
    for tag in node.select("script, style, nav, footer, header"):
        tag.decompose()
    text = re.sub(r"\n{3,}", "\n\n", node.get_text("\n", strip=True))
    if len(text) < 50:
        raise ValueError("抓取到的正文过短，可能被反爬拦截或页面需要登录。")
    return title, text[:12000], date  # 截断，避免超长


PARSE_SYSTEM = (
    "你是常旅客知识库的资料整理助手。用户会给你一篇文章的正文。"
    "请从中抽取与常旅客相关的知识，范围包括两大类："
    "①【规则与权益】航司里程/积分/权益/联盟、信用卡积分转点/返现/权益、酒店会员/积分；"
    "②【实用操作教程】开卡/激活、绑定支付方式（如绑定 Apple Pay、云闪付、微信支付宝）、"
    "还款方法、客服联系方式与验证步骤、各类操作流程——这些『怎么做』的教程同样重要，必须保留，不要当作无关内容剔除。"
    "只剔除纯广告、引流、无关闲聊。把内容按主题切分成若干条独立、自洽的知识片段。"
    "【极其重要·逐字保真】必须逐字保留原文中所有具体数字、百分比、比例、金额、里程数、天数、"
    "电话/卡号等联系方式、条件门槛和计算公式（如『0.4%基础回赠 + 2%赏世界 = 2.4%』『10:1』"
    "『客服电话 +852 2233 3000』等），严禁概括、省略或用『较少/很多/一些』等模糊词替代原文数字。"
    "宁可片段写长一点，也要把原文的具体数据和操作步骤完整带上。"
    "【极其重要·禁止杜撰】只抽取原文明确写出的信息；原文没有写的，绝不推断、脑补或补全。"
    "不确定、含糊或原文未提及的内容，宁可不抽，也不要编造。严禁把不同知识点的数字张冠李戴，"
    "严禁把『据说/可能』写成确定事实。保真优先于完整。"
    "【极其重要·枚举必须抽全】当原文出现并列的多档/多项枚举（如里程碑 50N/75N/100N 各档、"
    "会员各等级、多档返现比例、多个步骤）时，必须把同一组里【每一项都完整抽出】，"
    "不能只抽前几项就停。若同组枚举在你看到的这段文字里就是完整的，务必一项不漏地全部保留。"
    "【注意排版陷阱】原文常把列表序号紧贴内容数字（如『1.50N礼遇』其实是『第1项：50N礼遇』、"
    "『2.75N』是『第2项：75N』），绝不要把序号和数字粘成小数（不要读成 1.50、2.75）；"
    "遇到这种情况必须拆开还原成正确含义（如写成『50N礼遇』『75N礼遇』）。"
    "每条输出以下字段："
    "domain（只能是 airline / credit_card / hotel / other 之一；"
    "【跨域归类】若一条知识横跨多域（如『招行信用卡积分转东航里程』『Amex 转万豪积分』），"
    "按这条知识的【核心动作/主体】归类：核心讲『信用卡怎么转出/返现』归 credit_card，"
    "核心讲『航司里程怎么获取/使用』归 airline，核心讲『酒店积分/会籍』归 hotel）、"
    "subject（这条知识的【主体对象】，用最简短的品牌/对象名，如『万豪』『汇丰Pulse』『国航』"
    "『招商银行信用卡』；必须是这条知识真正在讲的主体，不能填正文里只是顺带提及的其它品牌）、"
    "subtopic（细分主题标签，用简短中文概括这条知识属于什么子类，如『返现比例』『绑定教程』"
    "『还款方式』『权益活动』『会籍规则』等，便于分类检索）、"
    "source（来源标签，必须【包含主体品牌】且【简短稳定】，格式建议『来源类型-主体-简述』，"
    "如『公众号-万豪-会员攻略』『公众号-汇丰Pulse-刷卡返现』；同一篇文章的所有片段 source 应保持一致；"
    "严禁编造与文章内容无关的来源名）、"
    "text（该片段正文，中文，逐字保留原文数字与步骤，完整）。"
    "只输出 JSON，格式：{\"fragments\":[{\"domain\":..,\"subject\":..,\"subtopic\":..,\"source\":..,\"text\":..}, ...]}。"
    "若文章与常旅客主题无关，返回 {\"fragments\":[]}。"
)


def _parse_chunk(title: str, text: str):
    """解析单块正文，返回清洗后的片段 list[dict]。"""
    resp = client.chat.completions.create(
        model=config.CHAT_MODEL,
        messages=[
            {"role": "system", "content": PARSE_SYSTEM},
            {"role": "user", "content": f"文章标题：{title}\n\n正文：\n{text}"},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {"fragments": []}
    frags = data.get("fragments", [])
    valid = {"airline", "credit_card", "hotel", "other"}
    out = []
    for f in frags:
        d = f.get("domain", "other")
        out.append({
            "domain": d if d in valid else "other",
            "subject": (f.get("subject") or "").strip()[:30],
            "subtopic": (f.get("subtopic") or "").strip()[:20],
            "source": f.get("source", title)[:60],
            "text": (f.get("text") or "").strip(),
        })
    return [f for f in out if f["text"]]


def _split_text(text: str, max_len: int = 1000):
    """按段落把长文切成不超过 max_len 的块（尽量在换行边界切，保持语义完整）。
    公众号正文常只有单换行，故先试双换行、切不动再退到单换行。"""
    if len(text) <= max_len:
        return [text]
    # 优先双换行；若整篇没有双换行（公众号常见），退回单换行
    paras = re.split(r"\n{2,}", text)
    if len(paras) == 1:
        paras = text.split("\n")
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > max_len:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def parse(title: str, text: str, on_progress=None):
    """把正文解析成结构化片段。长文分块 + 并行解析。
    on_progress(msg) 可选，用于上报进度。"""
    def _p(msg):
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    chunks = _split_text(text)
    if len(chunks) == 1:
        _p("AI 解析中…")
        return _parse_chunk(title, chunks[0])

    # 多块：并行解析
    _p(f"AI 解析中（共 {len(chunks)} 块）…")
    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as ex:
        futures = [ex.submit(_parse_chunk, title, c) for c in chunks]
        for fut in futures:
            try:
                results.extend(fut.result())
            except Exception:
                pass
            done += 1
            _p(f"AI 解析中 {done}/{len(chunks)} 块…")

    # 按 text 去重（不同块偶有重叠）
    seen, merged = set(), []
    for f in results:
        key = f["text"][:80]
        if key in seen:
            continue
        seen.add(key)
        merged.append(f)
    return merged


ALIAS_SYSTEM = (
    "你是常旅客问答系统的检索增强助手。给你一条知识片段，"
    "请站在【用户】角度，生成 3-5 个用户可能用来查询这条知识的、口语化且多样的问法。"
    "问法要覆盖不同表达习惯（如简称、口语、不同侧重），但都必须指向这条知识的核心信息。"
    "【关键要求】每个问法都必须包含这条知识的具体主题词/专有名词（如『万豪』『Pulse』『国航』"
    "『云闪付』等品牌或对象名），严禁生成『保级需要什么条件』『怎么算』这种缺少主语、"
    "会跨主题误匹配的泛化问法。若知识里有明确对象，问法必须带上它。"
    "【极其重要·防串味】问法里的主题词必须是这条知识真正在讲的【主体对象】，"
    "绝不能用正文里只是【顺带提及】的其它品牌/对象来造问法。"
    "例如：一条讲『汇丰 Pulse 卡刷卡返现』的知识，即使正文顺带提到万豪餐饮奖励，"
    "问法也只能围绕 Pulse/汇丰/刷卡返现，严禁生成『用 Apple Pay 能拿哪些万豪奖励』这类"
    "把顺带提及对象当主体的问法——它会让这条 Pulse 知识被『万豪』相关提问误命中。"
    "先判断这条知识的主体是什么，只用主体对象造问法。"
    "只输出 JSON：{\"queries\": [\"问法1\", \"问法2\", ...]}。"
)


def generate_aliases(text: str):
    """给一条知识生成多个用户问法（别名），返回 list[str]。失败返回 []。"""
    try:
        resp = client.chat.completions.create(
            model=config.CHAT_MODEL,
            messages=[
                {"role": "system", "content": ALIAS_SYSTEM},
                {"role": "user", "content": f"知识片段：\n{text}"},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
            timeout=30,
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        qs = data.get("queries", [])
        return [q.strip() for q in qs if isinstance(q, str) and q.strip()][:5]
    except Exception:
        return []


def generate_aliases_batch(texts):
    """并行给多条知识生成别名，返回 list[list[str]]，与输入等长。"""
    if not texts:
        return []
    results = [[] for _ in texts]
    with ThreadPoolExecutor(max_workers=min(6, len(texts))) as ex:
        futs = {ex.submit(generate_aliases, t): i for i, t in enumerate(texts)}
        for fut in futs:
            i = futs[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = []
    return results


# ---- 异步解析任务（供前端显示进度）----
_parse_tasks = {}
_parse_lock = threading.Lock()


def _new_parse_task():
    tid = uuid.uuid4().hex[:12]
    with _parse_lock:
        _parse_tasks[tid] = {"id": tid, "status": "running",
                             "progress": "开始…", "result": None, "error": None}
    return tid


def _upd_parse(tid, **kw):
    with _parse_lock:
        if tid in _parse_tasks:
            _parse_tasks[tid].update(kw)


def get_parse_task(tid):
    with _parse_lock:
        return dict(_parse_tasks[tid]) if tid in _parse_tasks else None


def _run_parse(tid, url):
    """后台：抓取 → 解析(报进度) → 去重检测，结果存任务。"""
    from app import store  # 局部导入避免循环依赖
    try:
        _upd_parse(tid, progress="抓取网页中…")
        title, text, date = fetch(url)

        def prog(msg):
            _upd_parse(tid, progress=msg)

        fragments = parse(title, text, on_progress=prog)
        canon = canonical_url(url)
        for f in fragments:
            f["url"] = canon
            f["date"] = date

        _upd_parse(tid, progress="检测重复中…")
        dups = store.find_duplicates([f["text"] for f in fragments])
        for f, dup in zip(fragments, dups):
            if dup:
                f["duplicate"] = dup

        result = {"url": url, "title": title, "raw_text": text, "fragments": fragments}
        _upd_parse(tid, status="done", progress="完成", result=result)
    except ValueError as e:
        _upd_parse(tid, status="error", error=str(e))
    except Exception as e:
        _upd_parse(tid, status="error", error=f"解析失败：{e}")


def parse_async(url):
    """启动异步解析，返回 task_id。"""
    tid = _new_parse_task()
    threading.Thread(target=_run_parse, args=(tid, url), daemon=True).start()
    return tid
