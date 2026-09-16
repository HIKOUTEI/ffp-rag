Page({
  data: {
    coverage: [
      { group: '航司', items: ['国航（凤凰知音）', '东航（东方万里行）'] },
      { group: '信用卡', items: ['美国运通（MR 积分）', '招商银行信用卡', '航空联名卡'] },
      { group: '酒店', items: ['希尔顿荣誉客会', '万豪旅享家'] },
    ],
  },
  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setActive('pages/about/about')
    }
  },
})
