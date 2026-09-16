// 后端地址与领域常量。
// 本地联调：把 BASE_URL 改回 http://127.0.0.1:8000，并在微信开发者工具
// 「详情 → 本地设置 → 不校验合法域名」勾上。
const BASE_URL = 'https://ffp.hikoutei.cn'

const DOMAIN_LABEL = {
  airline: '航司',
  credit_card: '信用卡',
  hotel: '酒店',
  personal_account: '我的账户',
  other: '其他',
}

module.exports = { BASE_URL, DOMAIN_LABEL }
