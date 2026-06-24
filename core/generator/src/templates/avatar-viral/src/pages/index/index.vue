<!--
  avatar-viral 模板 · index 首页（覆盖 base）。
  题材身份：AI 头像生成。强调"输入风格 → 生成 → 结果展示 → 分享解锁"。
  口径：当前按风格描述生成头像，照片仅占位、不参与生成（与 template.json
  input_fields.photo.drives_generation=false 一致），文案不得宣称上传照片驱动生成。
  token 契约与 base 一致：__APP_NAME__ / __APP_SUBTITLE__ / __APP_FEATURES_JSON__。
-->
<template>
  <view class="container avatar-viral">
    <view class="hero">
      <text class="title">__APP_NAME__</text>
      <text class="subtitle">__APP_SUBTITLE__</text>
      <text class="badge">AI 头像 · 一键生成</text>
    </view>
    <view class="avatar-preview">
      <view class="avatar-frame"><text class="avatar-ph">头像预览</text></view>
    </view>
    <view class="actions">
      <button class="btn-primary" @click="goToForm">输入风格，生成头像</button>
      <button class="btn-share" @click="shareUnlock">分享解锁高清头像</button>
    </view>
    <view class="features">
      <view class="feature-item" v-for="(f, i) in features" :key="i">
        <text class="feature-text">{{ f }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
const features = __APP_FEATURES_JSON__

function goToForm() {
  uni.navigateTo({ url: '/pages/form/form' })
}
function shareUnlock() {
  uni.showShareMenu({ withShareTicket: true } as any)
  uni.showToast({ title: '分享后解锁高清头像', icon: 'none' })
}
</script>

<style scoped>
.container { padding: 40rpx; min-height: 100vh; background: linear-gradient(160deg, #f3e8ff 0%, #f8f8f8 60%); }
.hero { text-align: center; padding: 60rpx 0 24rpx; }
.title { font-size: 44rpx; font-weight: bold; color: #1d1d1f; display: block; }
.subtitle { font-size: 28rpx; color: #6e6e73; margin-top: 12rpx; display: block; }
.badge { display: inline-block; margin-top: 16rpx; padding: 6rpx 20rpx; background: #7c3aed; color: #fff; border-radius: 999rpx; font-size: 22rpx; }
.avatar-preview { display: flex; justify-content: center; margin: 24rpx 0; }
.avatar-frame { width: 240rpx; height: 240rpx; border-radius: 50%; background: #ede9fe; border: 4rpx dashed #7c3aed; display: flex; align-items: center; justify-content: center; }
.avatar-ph { font-size: 26rpx; color: #7c3aed; }
.actions { text-align: center; margin: 32rpx 0; }
.btn-primary { background: #7c3aed; color: #fff; border: none; border-radius: 12rpx; padding: 24rpx 48rpx; font-size: 30rpx; }
.btn-share { margin-top: 20rpx; background: #fff; color: #7c3aed; border: 2rpx solid #7c3aed; border-radius: 12rpx; padding: 20rpx 48rpx; font-size: 28rpx; }
.features { padding: 20rpx; }
.feature-item { background: #fff; padding: 24rpx; margin-bottom: 16rpx; border-radius: 12rpx; }
.feature-text { font-size: 28rpx; color: #333; }
</style>
