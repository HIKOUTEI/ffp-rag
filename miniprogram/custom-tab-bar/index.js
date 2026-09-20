Component({
  data: {
    active: 'pages/chat/chat',
    // ⚠️ 顺序必须与 app.json 的 tabBar.list 一致，微信 tabBar 上限就是 5 个，
    //    加完「奖赏」再无空位。下一个要进 tab 的功能只能替换掉现有的某一个。
    list: [
      { value: 'pages/chat/chat', label: '问答', icon: 'chat' },
      { value: 'pages/rail/rail', label: '行程', icon: 'map-route-planning' },
      { value: 'pages/reward/reward', label: '奖赏', icon: 'wallet' },
      { value: 'pages/profile/profile', label: '我的', icon: 'user-circle' },
      { value: 'pages/about/about', label: '关于', icon: 'info-circle' },
    ],
  },
  methods: {
    onChange(e) {
      const path = e.detail.value
      wx.switchTab({ url: '/' + path })
    },
    // 由页面 onShow 调用，保证切页后高亮正确
    setActive(path) {
      this.setData({ active: path })
    },
  },
})
