"""Provider 配置 + 环境变量读取。所有 provider 走 OpenAI 兼容接口。"""
import os

from dotenv import load_dotenv

load_dotenv()

PROVIDERS = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "chat_model": "glm-4.5-air",          # 比 glm-4-flash 更聪明，价格仍低
        "embed_model": "embedding-3",
    },
    "openai": {
        "base_url": None,
        "chat_model": "gpt-4o-mini",
        "embed_model": "text-embedding-3-small",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "chat_model": "qwen-plus",
        "embed_model": "text-embedding-v3",
    },
}

PROVIDER = os.getenv("LLM_PROVIDER", "zhipu")
if PROVIDER not in PROVIDERS:
    raise SystemExit(f"未知 LLM_PROVIDER={PROVIDER}，可选: {', '.join(PROVIDERS)}")

CFG = PROVIDERS[PROVIDER]

API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

CHAT_MODEL = CFG["chat_model"]
EMBED_MODEL = CFG["embed_model"]
BASE_URL = CFG["base_url"]

# 路径
_HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(_HERE)
CORPUS_DIR = os.path.join(BACKEND_DIR, "corpus")
CHROMA_DIR = os.path.join(BACKEND_DIR, "chroma_db")
COLLECTION = "freq_flyer"
TOP_K = 4
