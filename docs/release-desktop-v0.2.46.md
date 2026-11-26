# desktop-v0.2.46

## 对话更宽敞，发送反馈更清楚 / More room for chat and clearer send feedback

- 优化桌面端窄窗口布局，为消息区留出更多空间。宽屏下标题、消息和输入框沿同一条阅读线排列，输入框随多行内容长高。
- 发送后立即显示消息和“正在生成回复…”。会话切换时，后台请求不会抢回页面或焦点，返回原会话也不会重复显示已保存的消息。
- 中文输入法确认候选时不发送消息；普通 Enter 发送，Shift+Enter 换行。发送被明确拒绝且输入框为空时会恢复原文，不自动重发。
- 改善键盘焦点和减少动态效果的体验，保留同一事实的纠正卡各自提交对应内容和来源的行为。

The desktop chat has a roomier narrow-window layout and immediate send feedback. Background replies no longer take over another conversation or duplicate saved messages on return. Enter sends only outside IME composition, Shift+Enter inserts a line break, and a rejected send restores the draft if the composer is empty.

## 验证范围 / Verification scope

Linux 打包版新增界面回归，覆盖合成数据下的会话切换、回复乱序、发送失败恢复、键盘操作和同一事实的两张纠正卡。输入法检查覆盖 Chromium 的合成输入事件，不等同于测试各系统的原生候选窗口。此版本不更改模型或训练逻辑。

Desktop prerelease only; Android is unchanged. Installers are unsigned and macOS builds are not notarized.
