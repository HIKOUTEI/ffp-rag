// 后端地址与领域常量。云部署后改这里的 BASE_URL 即可。
// 本地联调：微信开发者工具「详情 → 本地设置 → 不校验合法域名」勾上。
const BASE_URL = 'http://127.0.0.1:8000'

const DOMAIN_LABEL = {
  airline: '航司',
  credit_card: '信用卡',
  hotel: '酒店',
  personal_account: '我的账户',
  other: '其他',
}

module.exports = { BASE_URL, DOMAIN_LABEL }
