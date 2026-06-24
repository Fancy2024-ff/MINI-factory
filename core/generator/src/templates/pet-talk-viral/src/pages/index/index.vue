<!--
  pet-talk-viral 模板 · index 首页（覆盖 base）。
  题材身份：宠物说话预览。口径：当前按台词生成"会说话的宠物"预览/封面/海报，
  照片仅占位、不参与生成（template.json pet_photo.drives_generation=false），
  动态视频/配音为后续能力边界——文案不得宣称"生成视频/高清视频/完整视频"。
  token 契约与 base 一致。
-->
<template>
  <view class="container pet-talk-viral">
    <view class="hero">
      <text class="title">__APP_NAME__</text>
      <text class="subtitle">__APP_SUBTITLE__</text>
      <text class="badge">宠物说话 · 预览生成</text>
    </view>
    <view class="pet-stage">
      <view class="pet-frame"><text class="pet-ph">🐶 宠物说话预览</text></view>
    </view>
    <view class="actions">
      <button class="btn-primary" @click="goToForm">输入台词，生成预览</button>
      <button class="btn-share" @click="sharePreview">分享预览到朋友圈</button>
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
function sharePreview() {
  uni.showToast({ title: '宠物说话预览生成后可分享到朋友圈', icon: 'none' })
}
</script>

<style scoped>
.container { padding: 40rpx; min-height: 100vh; background: linear-gradient(160deg, #dcfce7 0%, #f8f8f8 60%); }
.hero { text-align: center; padding: 56rpx 0 20rpx; }
.title { font-size: 44rpx; font-weight: bold; color: #1d1d1f; display: block; }
.subtitle { font-size: 28rpx; color: #6e6e73; margin-top: 12rpx; display: block; }
.badge { display: inline-block; margin-top: 16rpx; padding: 6rpx 20rpx; background: #16a34a; color: #fff; border-radius: 999rpx; font-size: 22rpx; }
.pet-stage { display: flex; justify-content: center; margin: 24rpx 0; }
.pet-frame { width: 100%; height: 320rpx; background: #f0fdf4; border: 4rpx dashed #16a34a; border-radius: 16rpx; display: flex; align-items: center; justify-content: center; }
.pet-ph { font-size: 30rpx; color: #16a34a; }
.actions { text-align: center; margin: 28rpx 0; }
.btn-primary { background: #16a34a; color: #fff; border: none; border-radius: 12rpx; padding: 24rpx 48rpx; font-size: 30rpx; }
.btn-share { margin-top: 20rpx; background: #fff; color: #15803d; border: 2rpx solid #16a34a; border-radius: 12rpx; padding: 20rpx 48rpx; font-size: 28rpx; }
.features { padding: 20rpx; }
.feature-item { background: #fff; padding: 24rpx; margin-bottom: 16rpx; border-radius: 12rpx; }
.feature-text { font-size: 28rpx; color: #333; }
</style>
