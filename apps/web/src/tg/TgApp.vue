<!-- TG WebApp 根组件：轻量 pathname 路由（无 vue-router），ai-image 单页产品。 -->
<template>
  <div class="tg-root">
    <TgHome v-if="route === '/tg'" @navigate="navigate" />
    <AiImagePage v-else-if="route === '/tg/ai-image'" @navigate="navigate" />
    <AvatarPage v-else-if="route === '/tg/avatar'" @navigate="navigate" />
    <StickerPage v-else-if="route === '/tg/sticker'" @navigate="navigate" />
    <PetTalkPage v-else-if="route === '/tg/pet-talk'" @navigate="navigate" />
    <BgRemovePage v-else-if="route === '/tg/bg-remove'" @navigate="navigate" />
    <GeneratedFeaturePage
      v-else-if="route.startsWith('/tg/gen/')"
      :feature-id="route.replace('/tg/gen/', '')"
      @navigate="navigate"
    />
    <TgHome v-else @navigate="navigate" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import TgHome from './TgHome.vue'
import AiImagePage from './AiImagePage.vue'
import AvatarPage from './AvatarPage.vue'
import StickerPage from './StickerPage.vue'
import PetTalkPage from './PetTalkPage.vue'
import BgRemovePage from './BgRemovePage.vue'
import GeneratedFeaturePage from './GeneratedFeaturePage.vue'
import { initTelegram } from './telegram'
import { normalizeRoute } from './route'

const route = ref<string>(normalizeRoute(window.location.pathname))

function navigate(path: string) {
  const p = normalizeRoute(path)
  route.value = p
  try {
    window.history.pushState({}, '', p)
  } catch {
    /* 非浏览器环境忽略 */
  }
}

onMounted(() => {
  initTelegram()
  window.addEventListener('popstate', () => {
    route.value = normalizeRoute(window.location.pathname)
  })
})

defineExpose({ navigate })
</script>

<style scoped>
.tg-root { background: var(--tg-bg, #f7f7fa); min-height: 100vh; color: var(--tg-text, #1a1a1a); }
</style>
