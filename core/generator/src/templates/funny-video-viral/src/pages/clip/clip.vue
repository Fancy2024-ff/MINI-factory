<!--
  funny-video-viral 签名页：搞笑短视频「分镜脚本」工作台。模板身份页（base 没有）。
  边界：本模板产出 15 秒短视频的「脚本 / 分镜 / 封面预览」，不做复杂视频成片渲染。
-->
<template>
  <view class="container">
    <text class="page-title">搞笑视频脚本</text>
    <text class="page-sub">输入主题，秒出 15 秒分镜脚本，发起接龙挑战一起拍</text>

    <view class="notice">仅生成脚本 / 分镜 / 封面预览，不含复杂视频成片渲染</view>

    <view class="storyboard">
      <view class="shot" v-for="(s, i) in shots" :key="i">
        <text class="shot-time">{{ s.t }}</text>
        <text class="shot-desc">{{ s.desc }}</text>
      </view>
    </view>

    <view class="share-copy">「这个搞笑脚本我能笑一年」</view>

    <view class="actions">
      <button class="btn-primary" @click="startChallenge">发起接龙挑战</button>
      <button class="btn-share" open-type="share" @click="shareScript">分享脚本 · 解锁更多分镜模板</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'

// 分镜脚本（mock 预览；真实生成由后端 API 填充）
const shots = ref([
  { t: '0-3s', desc: '夸张开场，抛出反差设定' },
  { t: '3-9s', desc: '冲突升级，密集笑点' },
  { t: '9-15s', desc: '反转结尾 + 行动号召' },
])

function startChallenge() {
  uni.showToast({ title: '已发起接龙挑战', icon: 'none' })
}
function shareScript() {
  uni.showToast({ title: '分享后解锁更多分镜模板', icon: 'none' })
}
</script>

<style scoped>
.container { padding: 32rpx; min-height: 100vh; background: #fff7ed; }
.page-title { font-size: 36rpx; font-weight: 700; color: #111827; display: block; }
.page-sub { font-size: 26rpx; color: #6b7280; display: block; margin: 12rpx 0 16rpx; }
.notice { font-size: 22rpx; color: #be123c; background: #fff1f2; border-radius: 10rpx; padding: 14rpx 18rpx; margin-bottom: 24rpx; }
.storyboard { display: flex; flex-direction: column; gap: 16rpx; }
.shot { background: #fff; border-radius: 14rpx; padding: 24rpx; border-left: 6rpx solid #ef4444; }
.shot-time { font-size: 24rpx; color: #ef4444; font-weight: 600; display: block; }
.shot-desc { font-size: 28rpx; color: #333; display: block; margin-top: 8rpx; }
.share-copy { margin: 28rpx 0; text-align: center; font-size: 30rpx; color: #be123c; font-weight: 600; }
.actions { display: flex; flex-direction: column; gap: 16rpx; }
.btn-primary { background: #ef4444; color: #fff; border: none; border-radius: 12rpx; font-size: 30rpx; }
.btn-share { background: #fff; color: #be123c; border: 2rpx solid #fb7185; border-radius: 12rpx; font-size: 28rpx; }
</style>
