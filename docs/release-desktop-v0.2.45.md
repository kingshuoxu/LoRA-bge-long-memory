# desktop-v0.2.45

## 记忆纠正立即生效 / Immediate memory corrections

- 确认纠正后，明确指向该对象的提问立即使用当前事实，不必等待 LoRA 重训。训练启动失败和重启后仍保留纠正。
- 隔离旧适配器、旧事实索引及重复旧文档的冲突事实；保留同一对象其他未修改的事实。
- 来源标记指向实际纠正会话，记忆编辑不冒用当前聊天。错误旧记录不自动成为真实历史。
- 中英文界面显示已确认记忆和来源，不再误报“未调用记忆”；明确区分使用事实与挂载 LoRA。

Confirmed corrections take effect before retraining for supported named-subject/self questions, persist across restart and training startup failure, and retain their actual provenance. Stale adapters and conflicting retrieved facts cannot override the confirmed values. Chinese/English UI distinguishes confirmed-memory use from LoRA mounting.

## 验证与边界 / Verification and limits

专项验证包含 75 项 Python 和 6 项 UI 渲染回归；发布流水线还执行四平台安装包内纠正/重启契约与真实模型训练回归。现有 Linux GUI/迁移测试不等同于单独覆盖“训练中点击确认→新会话→查看来源”的完整交互路径。

训练期间无关生成仍需等待，已有训练/预览任务时暂不接受第二个纠正任务；歧义代词、自由创作和复杂时态不保证同等效果。独立纠正记录保护确认事实，不保证适配器注册中断时所有无关事实均可恢复。

Desktop only. No Android update. Packages remain unsigned; macOS is not notarized. Download integrity metadata is not a code-signing identity guarantee. This continues the existing desktop prerelease channel.
