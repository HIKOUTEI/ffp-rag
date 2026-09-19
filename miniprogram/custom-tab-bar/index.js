Component({
  data: {
    active: 'pages/chat/chat',
    list: [
      { value: 'pages/chat/chat', label: '问答', icon: 'chat' },
      { value: 'pages/rail/rail', label: '行程', icon: 'map-route-planning' },
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
