<!--
  blessing-video-viral 签名页：节日祝福贺卡工作台。模板身份页（base 没有）。
  边界：产出可分享的祝福贺卡 / 视频封面预览，真实视频合成为流程预留。
-->
<template>
  <view class="container">
    <text class="page-title">祝福贺卡</text>
    <text class="page-sub">选节日、填收件人和祝福语，一键生成可转发的祝福贺卡</text>

    <view class="notice">当前生成贺卡 / 视频封面预览，真实视频合成为流程预留</view>

    <view class="card-preview">
      <text class="card-festival">{{ card.festival }}</text>
      <text class="card-to">致 {{ card.to }}</text>
      <text class="card-msg">{{ card.message }}</text>
    </view>

    <view class="festivals">
      <text
        v-for="f in festivals" :key="f"
        class="festival-chip" :class="{ active: card.festival === f }"
        @click="card.festival = f"
      >{{ f }}</text>
    </view>

    <view class="actions">
      <button class="btn-primary" open-type="share" @click="sendToGroup">群发祝福给亲友</button>
      <button class="btn-share" @click="forwardCard">转发贺卡 · 解锁更多节日模板</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'

const festivals = ref(['新年', '春节', '生日', '中秋', '教师节'])
// 贺卡内容（mock 预览；真实生成由后端 API 填充）
const card = reactive({
  festival: '新年',
  to: '亲爱的朋友',
  message: '新的一年，愿你所求皆如愿，所行皆坦途。',
})

function sendToGroup() {
  uni.showToast({ title: '已生成群发祝福', icon: 'none' })
}
function forwardCard() {
  uni.showToast({ title: '转发后解锁更多节日模板', icon: 'none' })
}
</script>

<style scoped>
.container { padding: 32rpx; min-height: 100vh; background: linear-gradient(160deg, #fff7ed 0%, #fef9c3 60%); }
.page-title { font-size: 36rpx; font-weight: 700; color: #92400e; display: block; }
.page-sub { font-size: 26rpx; color: #b45309; display: block; margin: 12rpx 0 16rpx; }
.notice { font-size: 22rpx; color: #92400e; background: #fef3c7; border-radius: 10rpx; padding: 14rpx 18rpx; margin-bottom: 24rpx; }
.card-preview { background: radial-gradient(circle at top, #fff, #fffbeb); border: 2rpx solid #fbbf24; border-radius: 24rpx; padding: 48rpx 32rpx; text-align: center; box-shadow: 0 12rpx 36rpx rgba(217,119,6,0.16); }
.card-festival { font-size: 40rpx; font-weight: 800; color: #b45309; display: block; }
.card-to { font-size: 28rpx; color: #92400e; display: block; margin-top: 18rpx; }
.card-msg { font-size: 26rpx; color: #78716c; display: block; margin-top: 18rpx; line-height: 1.6; }
.festivals { display: flex; flex-wrap: wrap; gap: 14rpx; margin: 28rpx 0; }
.festival-chip { font-size: 26rpx; color: #92400e; background: #fff; border: 2rpx solid #fcd34d; border-radius: 999rpx; padding: 10rpx 26rpx; }
.festival-chip.active { background: #d97706; color: #fff; border-color: #d97706; }
.actions { display: flex; flex-direction: column; gap: 16rpx; }
.btn-primary { background: #d97706; color: #fff; border: none; border-radius: 12rpx; font-size: 30rpx; }
.btn-share { background: #fff; color: #92400e; border: 2rpx solid #f59e0b; border-radius: 12rpx; font-size: 28rpx; }
</style>
