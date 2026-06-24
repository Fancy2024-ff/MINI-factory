<!--
  ai-image 签名页 · canvas（base 没有）。
  口径：当前按文字描述生成图片，上传图片仅本地占位、不参与生成
  （template.json source_image.drives_generation=false）。
  本页只做"占位预览"，不暗示"上传图片处理成功"，真实生成走 form -> generation。
-->
<template>
  <view class="container">
    <view class="upload-card">
      <text class="title">参考图占位预览</text>
      <view class="upload-area" @click="chooseImage">
        <image v-if="imageUrl" :src="imageUrl" mode="aspectFit" class="preview-img" />
        <text v-else class="upload-hint">点击选择参考图（仅本地占位，不参与生成）</text>
      </view>
      <text class="note">当前按文字描述生成图片；上传图仅作本地占位预览，不会被处理或上传。</text>
      <button class="btn-process" @click="goGenerate">去按描述生成</button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const imageUrl = ref('')

function chooseImage() {
  uni.chooseImage({
    count: 1,
    success: (res) => { imageUrl.value = res.tempFilePaths[0] },
  })
}

// 真实生成走统一表单 -> generation 链路（描述驱动），本页不假装处理上传图。
function goGenerate() {
  uni.navigateTo({ url: '/pages/form/form' })
}
</script>

<style scoped>
.container { padding: 32rpx; min-height: 100vh; background: #f5f5f7; }
.upload-card { background: #fff; border-radius: 16rpx; padding: 32rpx; margin-bottom: 24rpx; }
.title { font-size: 34rpx; font-weight: 600; color: #1d1d1f; display: block; margin-bottom: 24rpx; }
.upload-area { width: 100%; height: 400rpx; background: #f5f5f7; border-radius: 12rpx; display: flex; align-items: center; justify-content: center; border: 2rpx dashed #d2d2d7; }
.preview-img { width: 100%; height: 100%; border-radius: 12rpx; }
.upload-hint { font-size: 26rpx; color: #aeaeb2; text-align: center; padding: 0 24rpx; }
.note { display: block; margin: 20rpx 0 0; font-size: 22rpx; color: #6e6e73; line-height: 1.5; }
.btn-process { margin-top: 24rpx; background: #0071e3; color: #fff; border: none; border-radius: 12rpx; font-size: 30rpx; }
</style>
