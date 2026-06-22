<!--
  可复用结果展示页：按 result id 读取 GeneratedResult，根据 previewType 渲染不同
  结果形态，提供分享 CTA + 分享解锁（去水印）+ 再生成入口。分享与解锁为本地 mock。
-->
<template>
  <view class="container">
    <view v-if="result" class="result-card">
      <text class="result-title">{{ result.title }}</text>
      <text class="result-template">模板：{{ result.template }}</text>

      <!-- 按 previewType 渲染不同结果形态 -->
      <view class="preview">
        <block v-if="result.previewType === 'avatar'">
          <text class="preview-note">{{ result.previewData.note }}</text>
          <view class="chip-row">
            <text v-for="(s, i) in result.previewData.styles" :key="i" class="chip">{{ s }}</text>
          </view>
        </block>
        <block v-else-if="result.previewType === 'stickerPack'">
          <text class="preview-note">主题：{{ result.previewData.theme }}（{{ result.previewData.count }} 张）</text>
          <view class="chip-row">
            <text v-for="(s, i) in result.previewData.stickers" :key="i" class="chip">{{ s }}</text>
          </view>
        </block>
        <block v-else-if="result.previewType === 'petVideo'">
          <text class="preview-note">台词：{{ result.previewData.line }}</text>
          <text class="preview-note">时长：{{ result.previewData.duration }}s（视频占位）</text>
        </block>
        <block v-else-if="result.previewType === 'funnyStoryboard'">
          <text class="preview-note">主题：{{ result.previewData.topic }}</text>
          <view v-for="(shot, i) in result.previewData.shots" :key="i" class="shot">
            <text class="shot-t">{{ shot.t }}</text>
            <text class="shot-d">{{ shot.desc }}</text>
          </view>
        </block>
        <block v-else-if="result.previewType === 'blessingCard'">
          <text class="preview-note">致 {{ result.previewData.to }}（{{ result.previewData.festival }}）</text>
          <text class="card-msg">{{ result.previewData.message }}</text>
        </block>
        <block v-else-if="result.previewType === 'image'">
          <view class="image-frame">
            <image
              v-if="result.previewData.image"
              class="result-image"
              :src="result.previewData.image"
              mode="aspectFit"
            />
            <image
              v-else-if="result.previewData.image_base64"
              class="result-image"
              :src="'data:image/png;base64,' + result.previewData.image_base64"
              mode="aspectFit"
            />
            <text v-else class="image-ph">图片生成中或暂无预览</text>
          </view>
          <text class="preview-note" v-if="result.previewData.prompt">描述：{{ result.previewData.prompt }}</text>
        </block>
        <block v-else>
          <text class="preview-note">{{ result.previewData.text }}</text>
        </block>
        <view v-if="result.watermarkEnabled" class="watermark">预览 · 含水印，分享后解锁高清无水印</view>
      </view>

      <!-- 分享文案 -->
      <view class="share-box">
        <text class="share-title">{{ result.shareTitle }}</text>
        <text class="share-copy">{{ result.shareCopy }}</text>
      </view>

      <!-- 分享 / 解锁 CTA -->
      <view class="actions">
        <button class="btn-share" open-type="share">分享作品</button>
        <button v-if="result.watermarkEnabled" class="btn-unlock" open-type="share" @click="handleUnlock">
          分享解锁高清/去水印/更多模板
        </button>
        <text v-else class="unlocked-tag">✓ 已解锁高清无水印</text>
      </view>
      <text class="unlock-hint">{{ result.unlockHint }}</text>

      <!-- 回流入口 -->
      <view class="footer">
        <button class="btn-regen" @click="regenerate">再生成一次</button>
        <button class="btn-home" @click="goHome">返回首页</button>
      </view>
    </view>

    <view v-else class="empty">
      <text>结果不存在或已过期，请重新生成。</text>
      <button class="btn-home" @click="goHome">返回首页</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { loadResult, unlockResult, type GeneratedResult } from '../../services/generation'

const result = ref<GeneratedResult | null>(null)

onLoad((options: any) => {
  const id = options?.id ? decodeURIComponent(options.id) : ''
  if (id) {
    result.value = loadResult(id)
  }
})

// 分享解锁（本地 mock）：解锁后去水印，本地状态变化
function handleUnlock() {
  if (!result.value) return
  const updated = unlockResult(result.value.id)
  if (updated) {
    result.value = { ...updated }
    uni.showToast({ title: '已解锁高清无水印', icon: 'success' })
  }
}

function regenerate() {
  uni.redirectTo({ url: '/pages/form/form' })
}

function goHome() {
  uni.switchTab ? uni.reLaunch({ url: '/pages/index/index' }) : uni.reLaunch({ url: '/pages/index/index' })
}
</script>

<style scoped>
.container { padding: 32rpx; min-height: 100vh; background: #f5f5f7; }
.result-card { background: #fff; border-radius: 16rpx; padding: 32rpx; }
.result-title { font-size: 34rpx; font-weight: 600; color: #1d1d1f; display: block; }
.result-template { font-size: 22rpx; color: #8e8e93; margin: 8rpx 0 24rpx; display: block; }
.preview { background: #f5f5f7; border-radius: 12rpx; padding: 24rpx; min-height: 160rpx; margin-bottom: 24rpx; position: relative; }
.preview-note { font-size: 28rpx; color: #333; display: block; margin-bottom: 12rpx; }
.chip-row { display: flex; flex-wrap: wrap; gap: 12rpx; }
.chip { background: #fff; border: 1rpx solid #d1d1d6; border-radius: 999rpx; padding: 6rpx 20rpx; font-size: 24rpx; color: #333; }
.shot { display: flex; gap: 16rpx; margin-bottom: 8rpx; }
.shot-t { font-size: 24rpx; color: #0071e3; width: 120rpx; }
.shot-d { font-size: 26rpx; color: #333; flex: 1; }
.card-msg { font-size: 30rpx; color: #d4380d; display: block; margin-top: 12rpx; }
.image-frame { width: 100%; height: 320rpx; border-radius: 12rpx; background: #ebebf0; border: 2rpx dashed #b0b0c0; display: flex; align-items: center; justify-content: center; margin-bottom: 12rpx; }
.image-ph { font-size: 26rpx; color: #8a8a9a; }
.result-image { width: 100%; height: 100%; border-radius: 12rpx; }
.watermark { margin-top: 16rpx; font-size: 22rpx; color: #b0b0b0; }
.share-box { background: #fff7e6; border-radius: 12rpx; padding: 20rpx; margin-bottom: 24rpx; }
.share-title { font-size: 28rpx; font-weight: 600; color: #d46b08; display: block; }
.share-copy { font-size: 24rpx; color: #ad6800; display: block; margin-top: 8rpx; }
.actions { display: flex; flex-direction: column; gap: 16rpx; }
.btn-share { background: #07c160; color: #fff; border: none; border-radius: 12rpx; font-size: 28rpx; }
.btn-unlock { background: #fa8c16; color: #fff; border: none; border-radius: 12rpx; font-size: 28rpx; }
.unlocked-tag { font-size: 26rpx; color: #07c160; text-align: center; }
.unlock-hint { font-size: 22rpx; color: #8e8e93; display: block; margin-top: 16rpx; }
.footer { display: flex; gap: 16rpx; margin-top: 32rpx; }
.btn-regen { flex: 1; background: #0071e3; color: #fff; border: none; border-radius: 12rpx; font-size: 28rpx; }
.btn-home { flex: 1; background: #f5f5f7; color: #333; border: 1rpx solid #d1d1d6; border-radius: 12rpx; font-size: 28rpx; }
.empty { padding: 80rpx 32rpx; text-align: center; color: #8e8e93; }
</style>
