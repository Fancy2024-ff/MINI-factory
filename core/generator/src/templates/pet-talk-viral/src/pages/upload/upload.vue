<!--
  pet-talk-viral 签名页：台词输入 + 照片占位。模板身份标识页（base 没有）。
  口径：照片仅占位、不参与生成；当前按台词生成"会说话的宠物"预览/封面。
  接入统一 mockGenerate（与 form 同一生成入口），生成后带 result.id 跳 result 页，
  不再跳无 id 的 result 断链页，CTA 只说生成预览、不夸大成动态视频。
-->
<template>
  <view class="container">
    <text class="page-title">宠物说话预览</text>
    <view class="upload-box" @click="pickPhoto">
      <text class="upload-ph">{{ photoPicked ? '照片已选（仅占位，不参与生成）' : '点击上传宠物照片（占位，可选）' }}</text>
    </view>
    <text class="hint">照片仅作占位，当前按下方台词生成会说话的宠物预览/封面。</text>
    <text class="label">想让它说什么</text>
    <textarea class="script-input" v-model="script" placeholder="例如：主人，该喂饭啦~" />
    <button class="btn-generate" @click="generate" :loading="loading" :disabled="loading">
      {{ loading ? '正在生成预览...' : '生成宠物说话预览' }}
    </button>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { mockGenerate } from '../../services/generation'

const script = ref('')
const photoPicked = ref(false)
const loading = ref(false)

function pickPhoto() {
  uni.chooseImage({
    count: 1,
    success: () => { photoPicked.value = true },
  } as any)
}

async function generate() {
  if (!script.value.trim()) {
    uni.showToast({ title: '请输入台词', icon: 'none' })
    return
  }
  loading.value = true
  try {
    // 照片仅占位：只把台词作为生成输入（assetPlaceholder 标注占位，不参与生成）。
    const result = await mockGenerate({
      text: script.value,
      assetPlaceholder: photoPicked.value ? '照片占位（不参与生成）' : '',
    })
    uni.navigateTo({ url: '/pages/result/result?id=' + encodeURIComponent(result.id) })
  } catch (e) {
    uni.showToast({ title: '生成失败，请重试', icon: 'none' })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.container { padding: 32rpx; min-height: 100vh; background: #f0fdf4; }
.page-title { font-size: 34rpx; font-weight: 600; color: #1d1d1f; display: block; margin-bottom: 24rpx; }
.upload-box { height: 280rpx; background: #fff; border: 4rpx dashed #16a34a; border-radius: 16rpx; display: flex; align-items: center; justify-content: center; }
.upload-ph { font-size: 28rpx; color: #16a34a; }
.hint { display: block; margin: 16rpx 0 0; font-size: 22rpx; color: #6e6e73; line-height: 1.5; }
.label { display: block; margin: 28rpx 0 12rpx; font-size: 28rpx; color: #333; }
.script-input { width: 100%; min-height: 160rpx; padding: 20rpx; background: #fff; border-radius: 12rpx; font-size: 28rpx; }
.btn-generate { margin-top: 32rpx; background: #16a34a; color: #fff; border: none; border-radius: 12rpx; font-size: 30rpx; }
</style>
