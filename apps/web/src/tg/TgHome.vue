<!-- MiniForge 工厂首页（Telegram WebApp）。ai-image / avatar 已开放，其余即将开放。 -->
<template>
  <div class="home">
    <header class="hero">
      <div class="logo">⚡ MiniForge</div>
      <h1 class="hero-title">AI 创意工厂</h1>
      <p class="hero-sub">一句话，生成你想要的画面</p>
    </header>

    <section class="cards">
      <button class="card card-open" @click="openAiImage">
        <div class="card-icon">🖼</div>
        <div class="card-body">
          <div class="card-title">AI 图片生成</div>
          <div class="card-desc">输入描述，选风格与比例，立即出图</div>
        </div>
        <div class="badge badge-open">已开放</div>
      </button>

      <button class="card card-open" @click="openAvatar">
        <div class="card-icon">🧑‍🎨</div>
        <div class="card-body">
          <div class="card-title">AI 头像</div>
          <div class="card-desc">文字生成社交头像 / 写真风格图</div>
        </div>
        <div class="badge badge-new">新上线</div>
      </button>

      <button class="card card-open" @click="openSticker">
        <div class="card-icon">😄</div>
        <div class="card-body">
          <div class="card-title">表情包工厂</div>
          <div class="card-desc">一个主题，生成一组搞怪贴纸</div>
        </div>
        <div class="badge badge-new">新上线</div>
      </button>

      <button class="card card-open" @click="openPetTalk">
        <div class="card-icon">🐶</div>
        <div class="card-body">
          <div class="card-title">宠物说话</div>
          <div class="card-desc">配一句台词，生成会说话的宠物预览</div>
        </div>
        <div class="badge badge-new">新上线</div>
      </button>

      <button class="card card-open" @click="openBgRemove">
        <div class="card-icon">✂️</div>
        <div class="card-body">
          <div class="card-title">背景去除</div>
          <div class="card-desc">上传图片，一键抠图去背景</div>
        </div>
        <div class="badge badge-new">新上线</div>
      </button>

      <div v-for="item in upcoming" :key="item.id" class="card card-soon">
        <div class="card-icon">{{ item.icon }}</div>
        <div class="card-body">
          <div class="card-title">{{ item.title }}</div>
          <div class="card-desc">{{ item.desc }}</div>
        </div>
        <div class="badge badge-soon">即将开放</div>
      </div>
    </section>

    <footer class="home-foot">更多能力正在路上，敬请期待</footer>
  </div>
</template>

<script setup lang="ts">
const emit = defineEmits<{ (e: 'navigate', path: string): void }>()

const upcoming = [
  { id: 'blessing', icon: '🎉', title: '祝福卡片', desc: '节日祝福，一键生成' },
]

function openAiImage() {
  emit('navigate', '/tg/ai-image')
}

function openAvatar() {
  emit('navigate', '/tg/avatar')
}

function openSticker() {
  emit('navigate', '/tg/sticker')
}

function openPetTalk() {
  emit('navigate', '/tg/pet-talk')
}

function openBgRemove() {
  emit('navigate', '/tg/bg-remove')
}
</script>

<style scoped>
.home { padding: 24px 16px 40px; max-width: 560px; margin: 0 auto; }
.hero { text-align: center; padding: 24px 0 28px; }
.logo { font-size: 15px; font-weight: 700; color: var(--tg-btn, #ff6b35); letter-spacing: 0.5px; }
.hero-title { font-size: 30px; font-weight: 800; margin: 12px 0 6px; color: var(--tg-text, #1a1a1a); }
.hero-sub { font-size: 15px; color: var(--tg-hint, #888); margin: 0; }
.cards { display: flex; flex-direction: column; gap: 12px; }
.card {
  display: flex; align-items: center; gap: 14px; width: 100%;
  padding: 18px 16px; border-radius: 16px; border: none; text-align: left;
  background: var(--tg-card, #fff); box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.card-open { cursor: pointer; }
.card-open:active { transform: scale(0.99); }
.card-soon { opacity: 0.62; }
.card-icon { font-size: 30px; width: 44px; text-align: center; }
.card-body { flex: 1; }
.card-title { font-size: 17px; font-weight: 700; color: var(--tg-text, #1a1a1a); }
.card-desc { font-size: 13px; color: var(--tg-hint, #888); margin-top: 3px; }
.badge { font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 999px; white-space: nowrap; }
.badge-open { background: #e8f7ee; color: #1a9c52; }
.badge-new { background: #f1eefe; color: #6c5ce7; }
.badge-soon { background: #f0f0f3; color: #999; }
.home-foot { text-align: center; font-size: 12px; color: var(--tg-hint, #aaa); margin-top: 28px; }
</style>
