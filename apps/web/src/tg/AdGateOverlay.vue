<!-- 看广告解锁下载的全屏遮罩。出图页共用，配合 useDownloadGate。 -->
<template>
  <div v-if="visible" class="ad-overlay">
    <div class="ad-box">📺</div>
    <div class="ad-countdown">{{ remain > 0 ? ('广告 ' + remain + 's') : '广告结束 ✓' }}</div>
    <div class="ad-hint">观看广告后即可下载高清图片</div>
    <button class="ad-skip" :disabled="remain > 0" @click="$emit('claim')">领取并下载</button>
  </div>
</template>

<script setup lang="ts">
defineProps<{ visible: boolean; remain: number }>()
defineEmits<{ (e: 'claim'): void }>()
</script>

<style scoped>
.ad-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 200; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #fff; padding: 24px; }
.ad-box { width: 100%; max-width: 420px; aspect-ratio: 16/10; background: linear-gradient(135deg,#1f2937,#374151); border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 40px; margin-bottom: 20px; }
.ad-countdown { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.ad-hint { font-size: 13px; color: #9ca3af; }
.ad-skip { margin-top: 18px; border: 1px solid #4b5563; color: #d1d5db; background: none; padding: 8px 18px; border-radius: 20px; }
.ad-skip:disabled { opacity: 0.4; }
</style>
