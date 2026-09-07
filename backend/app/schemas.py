"""API 请求/响应模型。"""
from typing import List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    top_k: int = 4


class Source(BaseModel):
    domain: str
    source: str
    score: float
    url: str = ""
    date: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: List[Source]


class Message(BaseModel):
    role: str      # user / assistant
    content: str


class ConversationRequest(BaseModel):
    messages: List[Message]   # 完整对话历史，最后一条是用户最新问题
    top_k: int = 6


class ConversationResponse(BaseModel):
    answer: str
    sources: List[Source]
    rewritten: str = ""       # 改写后的检索问题（调试/透明用）


class PopularQuestion(BaseModel):
    id: str
    text: str
    domain: str


class PopularQuestionsResponse(BaseModel):
    questions: List[PopularQuestion]


# ---- URL 摄入管线 ----

class ParseUrlRequest(BaseModel):
    url: str


class DuplicateInfo(BaseModel):
    """该片段与库中已有片段高度相似的提示。"""
    score: float
    source: str
    text: str
    date: str = ""
    url: str = ""


class Fragment(BaseModel):
    """AI 从网页解析出的一条知识片段。"""
    domain: str          # airline / credit_card / hotel / other
    subject: str = ""    # 主体对象品牌名，如「万豪」「汇丰Pulse」
    subtopic: str = ""   # 细分主题标签，如「返现比例」「绑定教程」
    source: str          # 如「公众号-XX里程规则」
    text: str
    url: str = ""        # 原文链接（种子语料为空）
    date: str = ""       # 文章发布日期 YYYY-MM-DD（种子语料为空）
    duplicate: Optional[DuplicateInfo] = None  # 疑似重复提示（仅 parse-url 返回时填充）


class ParseUrlResponse(BaseModel):
    url: str
    title: str
    fragments: List[Fragment]
    raw_text: str = ""   # 抓取到的纯文字原文，供人工对照


class IngestParsedRequest(BaseModel):
    fragments: List[Fragment]


class IngestParsedResponse(BaseModel):
    added: int
    total: int


class UpdateDocRequest(BaseModel):
    text: str
