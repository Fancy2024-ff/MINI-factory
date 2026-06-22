<!--
  Data-injected template page (single source of the form page structure).
  __APP_FEATURE_TITLE__ is substituted by BOTH generation consumers
  (core/pipeline/runner.py / core/generator/codegen.py and the Node page-builder)
  via the shared token contract. Do not re-author this markup in Python.

  交互闭环：收集输入 -> 调用 generation service 的 mockGenerate -> 保存结果 ->
  跳转 result 页并带 result id。
-->
<template>
  <view class="container">
    <view class="form-card">
      <text class="form-title">__APP_FEATURE_TITLE__</text>
      <view class="asset-slot" @click="pickAsset">
        <text class="asset-tip">{{ assetPlaceholder || '点击上传素材（占位，可选）' }}</text>
      </view>
      <textarea class="input-area" v-model="inputText" placeholder="请输入内容 / 主题 / 一句话..." />
      <button class="btn-submit" @click="handleSubmit" :loading="loading" :disabled="loading">
        {{ loading ? '正在生成...' : '开始生成' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { mockGenerate } from '../../services/generation'

const inputText = ref('')
const assetPlaceholder = ref('')
const loading = ref(false)

function pickAsset() {
  // 占位：真实场景接 uni.chooseImage / chooseMedia
  assetPlaceholder.value = '已选择素材（占位）'
  uni.showToast({ title: '已选择素材（占位）', icon: 'none' })
}

async function handleSubmit() {
  if (!inputText.value.trim() && !assetPlaceholder.value) {
    uni.showToast({ title: '请输入内容或上传素材', icon: 'none' })
    return
  }
  loading.value = true
  try {
    const result = await mockGenerate({
      text: inputText.value,
      assetPlaceholder: assetPlaceholder.value,
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
.container { padding: 32rpx; min-height: 100vh; background: #f5f5f7; }
.form-card { background: #fff; border-radius: 16rpx; padding: 32rpx; }
.form-title { font-size: 34rpx; font-weight: 600; color: #1d1d1f; margin-bottom: 24rpx; display: block; }
.asset-slot { border: 1rpx dashed #c7c7cc; border-radius: 12rpx; padding: 40rpx; text-align: center; margin-bottom: 24rpx; }
.asset-tip { font-size: 26rpx; color: #8e8e93; }
.input-area { width: 100%; min-height: 200rpx; padding: 20rpx; border: 1rpx solid #e8e8ed; border-radius: 12rpx; font-size: 28rpx; }
.btn-submit { margin-top: 32rpx; background: #0071e3; color: #fff; border: none; border-radius: 12rpx; font-size: 30rpx; }
</style>
