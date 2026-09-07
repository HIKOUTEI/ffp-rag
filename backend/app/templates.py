"""预设的规范问题模板。

既是小程序首屏冷启动的示例问题，也是热门榜（popular.py）统计与展示的单位。
用户每次真实提问会用 embedding 归到相似度最近的模板上。
分布：航司 4 / 信用卡 3 / 酒店 3。
"""

TEMPLATES = [
    # 航司
    {"id": "air-ca-benefits", "domain": "airline", "text": "国航金卡有哪些权益？"},
    {"id": "air-ca-miles-expire", "domain": "airline", "text": "国航里程多久过期？"},
    {"id": "air-ca-redeem-tokyo", "domain": "airline", "text": "国航里程换北京往返东京要多少里程？"},
    {"id": "air-mu-miles", "domain": "airline", "text": "东航里程有效期和联盟是什么？"},
    # 信用卡
    {"id": "card-cmb-transfer", "domain": "credit_card", "text": "招行信用卡积分怎么转成航司里程？"},
    {"id": "card-amex-transfer", "domain": "credit_card", "text": "美国运通积分能转哪些航司和酒店？"},
    {"id": "card-cobrand", "domain": "credit_card", "text": "航空联名信用卡有什么里程权益？"},
    # 酒店
    {"id": "hotel-marriott-transfer", "domain": "hotel", "text": "万豪积分怎么转成航司里程？"},
    {"id": "hotel-hilton-benefits", "domain": "hotel", "text": "希尔顿金卡和钻石卡有什么权益？"},
    {"id": "hotel-hilton-to-miles", "domain": "hotel", "text": "希尔顿积分能转航司里程吗划算吗？"},
]
