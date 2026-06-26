<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../services/api'

const platforms = ref<any[]>([])
const uploading = ref(false)
const uploadResult = ref<any>(null)

// 二级页：当前查看的平台 id（空串=一级平台列表）。
const viewPlatform = ref('')
const currentPlatformName = computed(() =>
  platforms.value.find((p) => p.platform_id === viewPlatform.value)?.platform_name || '',
)

// 已上架功能页（含预览 URL + 当前广告配置）。按平台归类挂到各平台卡片下。
const deployedApps = ref<any[]>([])
const appsLoaded = ref(false)
const savingRoute = ref('')
const uploadingVideoRoute = ref('')
const toast = ref('')

function showToast(msg: string) {
  toast.value = msg
  setTimeout(() => { if (toast.value === msg) toast.value = '' }, 1800)
}

// 取某平台下的已上架功能页。
function appsForPlatform(platformId: string) {
  return deployedApps.value.filter((a) => a.platform === platformId)
}

onMounted(async () => {
  try {
    const res = await api.getPlatformAuth()
    platforms.value = res.platforms
  } catch {}
  await loadDeployedApps()
})

async function loadDeployedApps() {
  try {
    const res = await api.getDeployedApps()
    deployedApps.value = (res.items || []).map((a: any) => ({
      ...a,
      _enabled: a.ad?.ad_enabled !== false,
      _seconds: a.ad?.ad_seconds ?? 30,
      _videoUrl: a.ad?.video_url || '',
    }))
  } catch {
    deployedApps.value = []
  } finally {
    appsLoaded.value = true
  }
}

async function saveApp(app: any) {
  savingRoute.value = app.route
  try {
    const secs = Math.max(0, Math.min(120, Number(app._seconds) || 0))
    const res = await api.saveAdConfig(app.route, app._enabled, secs)
    app._enabled = res.ad.ad_enabled
    app._seconds = res.ad.ad_seconds
    showToast(`已保存：${app.title}`)
  } catch {
    showToast('保存失败，请重试')
  } finally {
    savingRoute.value = ''
  }
}

// 上传广告视频：选中文件即上传，成功后回填 video_url。
async function onVideoPick(app: any, e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files && input.files[0]
  if (!file) return
  uploadingVideoRoute.value = app.route
  try {
    const res = await api.uploadAdVideo(app.route, file)
    app._videoUrl = res.video_url
    showToast(`广告视频已上传：${app.title}`)
  } catch {
    showToast('视频上传失败（仅支持 MP4/WebM，≤50MB）')
  } finally {
    uploadingVideoRoute.value = ''
    input.value = ''  // 允许再次选同名文件
  }
}

async function removeVideo(app: any) {
  uploadingVideoRoute.value = app.route
  try {
    await api.deleteAdVideo(app.route)
    app._videoUrl = ''
    showToast('已移除广告视频')
  } catch {
    showToast('移除失败，请重试')
  } finally {
    uploadingVideoRoute.value = ''
  }
}

// 视频相对路径拼成可播放绝对地址（dashboard 与后端可能不同源）。
function videoSrc(url: string): string {
  if (!url) return ''
  return url.startsWith('/') ? (import.meta.env.VITE_API_BASE_URL || '') + url : url
}

async function handleUpload(platformId: string) {
  if (platformId !== 'wechat') return
  uploading.value = true
  uploadResult.value = null
  try {
    uploadResult.value = await api.uploadWechat()
  } catch (e: any) {
    uploadResult.value = { upload_passed: false, reason: e.message }
  }
  uploading.value = false
}
</script>

<template>
  <div class="submit-center">
    <div class="header">
      <h3>提交中心</h3>
      <p class="subtitle">管理平台授权状态、自动上传和审核提交</p>
    </div>

    <div v-if="platforms.length === 0" class="empty">
      <p>暂无平台授权配置。请在 data/platform-auth/ 下添加配置文件。</p>
    </div>

    <!-- 一级页：平台列表（每个平台卡片底部有「已上架的小程序 ›」入口） -->
    <template v-if="!viewPlatform">
    <div v-for="plat in platforms" :key="plat.platform_id" class="platform-card">
      <div class="platform-header">
        <h4>{{ plat.platform_name }}</h4>
        <span class="config-badge" :class="plat.configured ? 'badge-ok' : 'badge-no'">
          {{ plat.configured ? '已配置' : '未配置' }}
        </span>
      </div>

      <!-- One-time setup -->
      <div v-if="plat.one_time_setup?.length" class="setup-list">
        <div class="setup-title">一次性配置</div>
        <div v-for="s in plat.one_time_setup" :key="s.name" class="setup-item">
          <span class="setup-dot" :class="s.done ? 'dot-done' : 'dot-pending'"></span>
          <span>{{ s.name }}</span>
        </div>
      </div>

      <!-- Missing config -->
      <div v-if="plat.missing_config?.length" class="missing-list">
        <div class="missing-title">缺失配置</div>
        <span v-for="m in plat.missing_config" :key="m" class="missing-chip">{{ m }}</span>
      </div>

      <!-- 自动化能力 -->
      <div v-if="plat.automation_actions?.length" class="actions-list">
        <div class="actions-title">自动化能力</div>
        <div v-for="a in plat.automation_actions" :key="a.name" class="action-item">
          <span class="action-dot" :class="a.enabled ? 'dot-done' : 'dot-pending'"></span>
          <span>{{ a.name }}</span>
          <span v-if="!a.enabled" class="action-disabled">未启用</span>
        </div>
      </div>

      <!-- Human actions required -->
      <div v-if="plat.human_actions?.length" class="human-list">
        <div class="human-title">需要人工操作</div>
        <div v-for="h in plat.human_actions" :key="h.name" class="human-item">
          <span>{{ h.name }}</span>
          <span class="human-reason">{{ h.reason }}</span>
        </div>
      </div>

      <!-- Upload button (wechat only for now) -->
      <div v-if="plat.platform_id === 'wechat'" class="upload-section">
        <button
          class="upload-btn"
          :disabled="!plat.can_upload || uploading"
          @click="handleUpload('wechat')"
        >
          {{ uploading ? '上传中...' : plat.can_upload ? '自动上传代码' : '上传不可用（需配置）' }}
        </button>
        <div v-if="uploadResult" class="upload-result" :class="uploadResult.upload_passed ? 'result-ok' : 'result-fail'">
          {{ uploadResult.upload_passed ? '上传成功' : uploadResult.reason }}
        </div>
      </div>

      <!-- 已上架小程序入口：点右侧箭头进二级页查看该平台的功能页 + 广告管理 -->
      <button class="apps-entry" @click="viewPlatform = plat.platform_id">
        <div class="apps-entry-text">
          <span class="apps-entry-title">已上架的小程序</span>
          <span class="apps-entry-count">{{ appsForPlatform(plat.platform_id).length }} 个功能页</span>
        </div>
        <span class="apps-entry-arrow">›</span>
      </button>
    </div>
    </template>

    <!-- 二级页：某平台下的已上架小程序（预览 + 广告上下架 + 时长 + 广告视频） -->
    <div v-else class="apps-detail">
      <button class="detail-back" @click="viewPlatform = ''">← 返回平台列表</button>
      <h3 class="detail-title">{{ currentPlatformName }} · 已上架的小程序</h3>
      <div v-if="appsLoaded && appsForPlatform(viewPlatform).length === 0" class="apps-empty">
        该平台暂无已上架的功能页。
      </div>
      <div class="apps-grid">
        <div v-for="app in appsForPlatform(viewPlatform)" :key="app.route" class="app-card">
          <div class="app-preview">
            <iframe :src="app.preview_url" :title="app.title" loading="lazy" referrerpolicy="no-referrer"></iframe>
          </div>
          <div class="app-body">
            <div class="app-title">
              <span class="app-icon">{{ app.icon }}</span>
              <strong>{{ app.title }}</strong>
              <span class="app-source" :class="app.source === 'generated' ? 'src-gen' : 'src-builtin'">
                {{ app.source === 'generated' ? '工厂生成' : '内置' }}
              </span>
            </div>
            <a class="app-open" :href="app.preview_url" target="_blank" rel="noopener">↗ 新窗口打开预览</a>

            <div class="ad-controls">
              <label class="ad-row">
                <span>广告（看完才能下载）</span>
                <button class="toggle" :class="{ on: app._enabled }" @click="app._enabled = !app._enabled">
                  {{ app._enabled ? '已上架' : '已下架' }}
                </button>
              </label>
              <label class="ad-row" :class="{ disabled: !app._enabled }">
                <span>广告时长（秒）</span>
                <input type="number" min="0" max="120" v-model.number="app._seconds" :disabled="!app._enabled" />
              </label>

              <!-- 广告视频：上传后作为该功能页的视频广告（替换倒计时黑屏） -->
              <div class="ad-video-row">
                <div class="ad-video-label">广告视频</div>
                <video v-if="app._videoUrl" class="ad-video-preview" :src="videoSrc(app._videoUrl)" controls muted></video>
                <div class="ad-video-actions">
                  <label class="video-upload-btn">
                    {{ uploadingVideoRoute === app.route ? '上传中…' : (app._videoUrl ? '替换视频' : '上传视频') }}
                    <input type="file" accept="video/mp4,video/webm" hidden
                           :disabled="uploadingVideoRoute === app.route"
                           @change="onVideoPick(app, $event)" />
                  </label>
                  <button v-if="app._videoUrl" class="video-remove-btn"
                          :disabled="uploadingVideoRoute === app.route" @click="removeVideo(app)">移除</button>
                </div>
                <div class="ad-video-hint">支持 MP4 / WebM，≤50MB。未上传则用倒计时广告。</div>
              </div>

              <button class="save-btn" :disabled="savingRoute === app.route" @click="saveApp(app)">
                {{ savingRoute === app.route ? '保存中…' : '保存广告设置' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>

<style scoped>
.submit-center { animation: fadeIn 0.3s ease; }
.header { margin-bottom: 20px; }
.header h3 { font-size: 20px; font-weight: 600; color: var(--color-text-1); }
.subtitle { font-size: 13px; color: var(--color-text-2); margin-top: 4px; }
.empty { padding: 40px; text-align: center; color: var(--color-text-3); }

.platform-card { background: var(--color-surface-solid); border-radius: var(--radius-lg); padding: 20px; margin-bottom: 16px; box-shadow: var(--shadow-card); }
.platform-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.platform-header h4 { font-size: 15px; font-weight: 600; color: var(--color-text-1); }
.config-badge { font-size: 11px; font-weight: 500; padding: 3px 8px; border-radius: 10px; }
.badge-ok { background: var(--color-green-subtle); color: #166534; }
.badge-no { background: rgba(255,59,48,0.08); color: #991b1b; }

.setup-list, .missing-list, .actions-list, .human-list { margin-bottom: 12px; }
.setup-title, .missing-title, .actions-title, .human-title { font-size: 11px; font-weight: 600; color: var(--color-text-3); text-transform: uppercase; margin-bottom: 6px; }
.setup-item, .action-item { display: flex; align-items: center; gap: 6px; font-size: 13px; padding: 3px 0; color: var(--color-text-1); }
.setup-dot, .action-dot { width: 8px; height: 8px; border-radius: 50%; }
.dot-done { background: var(--color-green); }
.dot-pending { background: var(--color-text-3); }
.action-disabled { font-size: 11px; color: var(--color-text-3); margin-left: auto; }

.missing-chip { font-size: 11px; padding: 2px 6px; background: rgba(255,59,48,0.08); color: #991b1b; border-radius: 4px; margin-right: 4px; }

.human-item { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; }
.human-reason { font-size: 11px; color: var(--color-text-3); }

.upload-section { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--color-border); }
.upload-btn { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 500; background: var(--color-blue); color: #fff; border: none; cursor: pointer; }
.upload-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.upload-result { margin-top: 8px; font-size: 12px; padding: 6px 10px; border-radius: 6px; }
.result-ok { background: var(--color-green-subtle); color: #166534; }
.result-fail { background: rgba(255,59,48,0.08); color: #991b1b; }

/* 一级页：平台卡片底部的「已上架的小程序 ›」入口 */
.apps-entry { width: 100%; margin-top: 16px; padding: 14px 16px; border: none; border-top: 1px solid var(--color-border); background: none; display: flex; align-items: center; justify-content: space-between; cursor: pointer; border-radius: 0 0 var(--radius-lg) var(--radius-lg); }
.apps-entry:hover { background: var(--color-fill-1, rgba(0,0,0,0.02)); }
.apps-entry-text { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
.apps-entry-title { font-size: 14px; font-weight: 600; color: var(--color-text-1); }
.apps-entry-count { font-size: 12px; color: var(--color-text-3); }
.apps-entry-arrow { font-size: 22px; color: var(--color-text-3); line-height: 1; }

/* 二级页 */
.detail-back { border: none; background: none; color: var(--color-blue); font-size: 13px; cursor: pointer; padding: 0; margin-bottom: 12px; }
.detail-title { font-size: 18px; font-weight: 600; color: var(--color-text-1); margin-bottom: 16px; }
.apps-empty { font-size: 13px; color: var(--color-text-3); padding: 8px 0; }
.apps-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.app-card { background: var(--color-surface-solid); border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-card); display: flex; flex-direction: column; }
.app-preview { width: 100%; aspect-ratio: 9 / 14; background: #f0f0f3; overflow: hidden; border-bottom: 1px solid var(--color-border); }
.app-preview iframe { width: 100%; height: 100%; border: 0; display: block; }
.app-body { padding: 14px; }
.app-title { display: flex; align-items: center; gap: 8px; }
.app-title strong { font-size: 15px; color: var(--color-text-1); }
.app-icon { font-size: 18px; }
.app-source { margin-left: auto; font-size: 10px; padding: 2px 6px; border-radius: 6px; }
.src-builtin { background: rgba(0,0,0,0.05); color: var(--color-text-3); }
.src-gen { background: rgba(108,92,231,0.1); color: #6c5ce7; }
.app-open { display: inline-block; margin-top: 6px; font-size: 12px; color: var(--color-blue); text-decoration: none; }
.app-open:hover { text-decoration: underline; }

.ad-controls { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--color-border); display: flex; flex-direction: column; gap: 10px; }
.ad-row { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: var(--color-text-1); }
.ad-row.disabled { opacity: 0.5; }
.ad-row input { width: 72px; padding: 5px 8px; border: 1px solid var(--color-border); border-radius: 8px; font-size: 13px; text-align: right; }
.toggle { padding: 5px 12px; border-radius: 999px; border: none; font-size: 12px; font-weight: 600; cursor: pointer; background: rgba(0,0,0,0.06); color: var(--color-text-3); }
.toggle.on { background: var(--color-green-subtle); color: #166534; }
.save-btn { margin-top: 2px; padding: 8px; border-radius: 8px; border: none; background: var(--color-blue); color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; }
.save-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.ad-video-row { display: flex; flex-direction: column; gap: 8px; padding-top: 8px; border-top: 1px dashed var(--color-border); }
.ad-video-label { font-size: 13px; color: var(--color-text-1); }
.ad-video-preview { width: 100%; max-height: 120px; border-radius: 8px; background: #000; }
.ad-video-actions { display: flex; gap: 8px; }
.video-upload-btn { flex: 1; text-align: center; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--color-blue); color: var(--color-blue); font-size: 12px; font-weight: 600; cursor: pointer; }
.video-remove-btn { padding: 7px 12px; border-radius: 8px; border: 1px solid rgba(255,59,48,0.4); background: none; color: #991b1b; font-size: 12px; cursor: pointer; }
.video-remove-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ad-video-hint { font-size: 11px; color: var(--color-text-3); }
.toast { position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%); background: rgba(0,0,0,0.82); color: #fff; padding: 10px 20px; border-radius: 999px; font-size: 14px; z-index: 50; }

@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
</style>
