<!--
  可复用结果展示页：按 result id 读取 GeneratedResult，根据 previewType 渲染不同
  结果形态，提供分享 CTA + 分享解锁（去水印）+ 再生成入口。分享与解锁为本地 mock。
-->
<template>
  <view class="container">
    <view v-if="result" class="result-card">
      <text class="result-title">{{ result.title }}</text>
      <text class="result-template">模板：{{ result.template }} · {{ result.previewType }}</text>

      <!-- 模板能力真实状态：核心可跑通 / honest fallback preview，口径与 blueprint/QA 一致 -->
      <view class="status-bar" :class="isCore ? 'status-bar--core' : 'status-bar--preview'">
        <text class="status-badge">{{ statusLabel }}</text>
        <text class="status-line">真实生成：{{ result.realGeneration ? '是' : '否' }}</text>
        <text class="status-line" v-if="result.fallbackMode">模式：{{ result.apiFailed ? 'API 失败降级预览' : 'honest fallback / preview mode' }}</text>
      </view>
      <text v-if="!isCore && nonCoreHint" class="boundary-note">
        {{ nonCoreHint }}
      </text>
      <text v-if="result.boundaryNote && result.boundaryNote !== nonCoreHint" class="boundary-note boundary-note--muted">{{ result.boundaryNote }}</text>

      <!-- 醒目 preview mode 提示：capabilityMode === fallback_preview 时强提示当前为预览，非真实成片 -->
      <view v-if="isPreviewMode" class="preview-banner">
        <text class="preview-banner-title">⚠ Preview Mode · 预览模式</text>
        <text class="preview-banner-text">{{ result.capabilityNote || nonCoreHint }}</text>
      </view>

      <!-- 传播闭环 / Growth Loop：分享 / 解锁 / 水印 / 去水印 / 品牌 / 导出 / 能力，全部来自事实源 -->
      <view class="growth-loop" v-if="result.growthLoop">
        <text class="growth-loop-title">传播闭环 · Growth Loop</text>
        <view class="gl-row">
          <text class="gl-key">分享 CTA</text>
          <text class="gl-val">{{ result.hasShareCta ? ('有 · ' + (result.shareCtaLabel || '分享')) : '无' }}</text>
        </view>
        <view class="gl-row">
          <text class="gl-key">解锁机制</text>
          <text class="gl-val">{{ result.hasUnlock ? ('有 · ' + (result.unlockHint || result.unlockType || '')) : '无' }}</text>
        </view>
        <view class="gl-row">
          <text class="gl-key">水印</text>
          <text class="gl-val">{{ result.hasWatermark ? ('有 · ' + (result.watermarkLabel || '水印')) : '无' }}</text>
        </view>
        <view class="gl-row">
          <text class="gl-key">去水印</text>
          <text class="gl-val">{{ result.removeWatermarkSupported ? ('支持 · ' + (result.removeWatermarkCondition || '分享解锁')) : '暂不支持' }}</text>
        </view>
        <view class="gl-row">
          <text class="gl-key">品牌露出</text>
          <text class="gl-val">{{ result.brandExposure ? ('有 · ' + (result.brandLabel || '')) : '无' }}</text>
        </view>
        <view class="gl-row">
          <text class="gl-key">下载 / 导出</text>
          <text class="gl-val">{{ result.exportSupported ? ('支持 · ' + (result.exportLabel || '导出')) : '导出入口已预留' }}</text>
        </view>
        <view class="gl-row">
          <text class="gl-key">当前能力</text>
          <text class="gl-val" :class="isPreviewMode ? 'gl-val--preview' : 'gl-val--real'">
            {{ isPreviewMode ? 'fallback_preview · 预览模式' : 'real · 真实生成' }}
          </text>
        </view>
        <text v-if="result.capabilityNote" class="gl-note">{{ result.capabilityNote }}</text>
      </view>


      <!-- 按 previewType 渲染不同结果形态 -->
      <view class="preview">
        <!-- 通用真实图片块：真实 API 成功后 previewData 带 image/image_base64 时，
             对 avatar/stickerPack/petVideo 这类「题材分支本身不画图」的 previewType
             也展示真实生成图，不再只把真实结果存进 storage 却不可见。
             （image 类型有自己的图片块 + 占位逻辑，这里排除避免重复渲染。） -->
        <view v-if="hasRealImage && result.previewType !== 'image'" class="image-frame">
          <image
            v-if="result.previewData.image"
            class="result-image"
            :src="result.previewData.image"
            mode="aspectFit"
          />
          <image
            v-else
            class="result-image"
            :src="'data:image/png;base64,' + result.previewData.image_base64"
            mode="aspectFit"
          />
        </view>

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
          <text class="preview-note">宠物说话预览 / 封面已生成（动态视频为后续增强）</text>
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
        <view v-if="result.watermarkEnabled" class="watermark">{{ watermarkText }}</view>
      </view>

      <!-- 分享文案 -->
      <view class="share-box">
        <text class="share-title">{{ result.shareTitle }}</text>
        <text class="share-copy">{{ result.shareCopy }}</text>
      </view>

      <!-- 分享 / 解锁 CTA：按事实源 hasShareCta / hasUnlock / removeWatermarkSupported 控制显示 -->
      <view class="actions">
        <button v-if="result.hasShareCta !== false" class="btn-share" open-type="share">{{ result.shareCtaLabel || '分享作品' }}</button>
        <!-- 去水印型解锁：有解锁 + 当前有水印 + 支持去水印 -->
        <button
          v-if="canRemoveWatermark"
          class="btn-unlock"
          open-type="share"
          @click="handleUnlock"
        >
          {{ result.unlockHint || '分享解锁去水印' }}
        </button>
        <!-- 已去水印 -->
        <text v-else-if="result.hasWatermark !== false && !result.watermarkEnabled" class="unlocked-tag">✓ 已解锁高清无水印</text>
        <!-- 有解锁但不支持去水印：分享解锁内容/更多模板，绝不承诺去水印 -->
        <button
          v-else-if="result.hasUnlock !== false && result.removeWatermarkSupported === false"
          class="btn-unlock"
          open-type="share"
          @click="handleUnlock"
        >
          {{ result.unlockHint || '分享解锁更多内容' }}
        </button>
        <button v-if="result.exportSupported && canExport" class="btn-export" @click="handleExport">
          {{ result.exportLabel || '导出 / 下载' }}
        </button>
        <text v-else-if="result.exportSupported && !canExport" class="export-hint">{{ result.exportLabel || '导出暂不可用' }}</text>
      </view>
      <text class="unlock-hint" v-if="result.hasUnlock !== false">{{ result.unlockHint }}</text>

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
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { loadResult, unlockResult, classifyExportTarget, type GeneratedResult } from '../../services/generation'

const result = ref<GeneratedResult | null>(null)

// 核心可跑通模板（真实生成且非降级）；否则视为 honest fallback / preview。
const isCore = computed(() =>
  result.value?.templateStatus === 'core_runnable' &&
  result.value?.realGeneration === true &&
  !result.value?.fallbackMode,
)

const statusLabel = computed(() => {
  if (!result.value) return ''
  if (result.value.apiFailed) return 'API 失败 · 临时预览'
  if (isCore.value) return '核心可跑通 · 真实生成'
  return 'honest fallback · preview mode'
})

// 是否视频边界型模板（funny-video / blessing-video）。只有它们才允许出现
// 「真实视频生成是后续能力边界」这类视频专属提示，其它模板不得套用该文案。
const isVideoBoundaryTemplate = computed(() => {
  const t = result.value?.template || ''
  return t === 'funny-video-viral' || t === 'blessing-video-viral'
})

// 非核心结果的提示文案：优先用事实源 boundaryNote / capabilityNote；
// 仅视频边界型模板在缺少事实源文案时，才回退到「真实视频生成是后续能力边界」。
const nonCoreHint = computed(() => {
  if (!result.value) return ''
  if (result.value.apiFailed) {
    return result.value.capabilityNote || result.value.fallbackReason || '真实生成暂时不可用，已临时回退本地预览'
  }
  if (result.value.boundaryNote) return result.value.boundaryNote
  if (result.value.capabilityNote) return result.value.capabilityNote
  if (isVideoBoundaryTemplate.value) {
    return '当前为 honest fallback / preview mode，真实视频生成是后续能力边界'
  }
  return '当前为 honest fallback / preview mode，展示为预览结果'
})

// 能力模式：fallback_preview（含 API 失败降级、视频边界型）显示醒目预览提示。
const isPreviewMode = computed(() =>
  result.value?.capabilityMode === 'fallback_preview' || result.value?.apiFailed === true,
)

// 是否有真实生成图（真实 API 成功后 previewData.image / image_base64 非空）。
// avatar/stickerPack/petVideo 的题材分支本身不画图，靠这个通用块把真实图渲染出来。
const hasRealImage = computed(() => {
  const pd = result.value?.previewData
  return !!(pd && (pd.image || pd.image_base64))
})

// 是否可去水印解锁：有解锁机制 + 当前确有水印 + 事实源支持去水印。
const canRemoveWatermark = computed(() =>
  result.value?.hasUnlock !== false &&
  result.value?.watermarkEnabled === true &&
  result.value?.removeWatermarkSupported !== false,
)

// 是否真有可执行导出路径（与 handleExport 同源判定）。exportSupported=true 但分类为 none
// 时（理论上不该发生，双保险），不显示可点击导出按钮，避免假承诺。
const canExport = computed(() =>
  !!result.value && classifyExportTarget(result.value).kind !== 'none',
)

// 水印文案：优先用事实源 watermarkLabel，回退通用文案。
const watermarkText = computed(() => {
  const label = result.value?.watermarkLabel
  return label ? `预览 · 含「${label}」，分享后解锁去水印` : '预览 · 含水印，分享后解锁高清无水印'
})

onLoad((options: any) => {
  const id = options?.id ? decodeURIComponent(options.id) : ''
  if (id) {
    result.value = loadResult(id)
  }
})

// 分享解锁（本地 mock）：按 growth_loop 去水印能力决定结果，不假装去掉不支持去水印的水印。
function handleUnlock() {
  if (!result.value) return
  const updated = unlockResult(result.value.id)
  if (updated) {
    result.value = { ...updated }
    const removed = updated.watermarkEnabled === false
    uni.showToast({
      title: removed ? '已解锁高清无水印' : '已分享解锁',
      icon: 'success',
    })
  }
}

// 导出 / 下载：诚实可用 MVP。导出目标由纯函数 classifyExportTarget 判定（与单测同源），
// 不再让 UI 自己零散判断，避免「exportSupported=true 但点击不可用」的假承诺。
// - remote_image：downloadFile + saveImageToPhotosAlbum，真存相册；
// - text（脚本/祝福卡/通用文本）：setClipboardData 复制，真实可用；
// - none（仅 base64 无 URL / 无可导出内容）：诚实提示不可导出，绝不假装成功。
function handleExport() {
  if (!result.value) return
  const target = classifyExportTarget(result.value)

  if (target.kind === 'remote_image' && target.image) {
    uni.showLoading({ title: '正在保存…' })
    uni.downloadFile({
      url: target.image,
      success: (d: any) => {
        if (d.statusCode !== 200 || !d.tempFilePath) {
          uni.hideLoading()
          uni.showToast({ title: '下载失败，请稍后重试', icon: 'none' })
          return
        }
        uni.saveImageToPhotosAlbum({
          filePath: d.tempFilePath,
          success: () => {
            uni.hideLoading()
            uni.showToast({ title: '已保存到相册', icon: 'success' })
          },
          fail: () => {
            uni.hideLoading()
            uni.showToast({ title: '保存失败，请允许相册权限后重试', icon: 'none' })
          },
        })
      },
      fail: () => {
        uni.hideLoading()
        uni.showToast({ title: '下载失败，请稍后重试', icon: 'none' })
      },
    })
    return
  }

  if (target.kind === 'text' && target.text) {
    uni.setClipboardData({
      data: target.text,
      success: () => uni.showToast({ title: '已复制到剪贴板', icon: 'success' }),
      fail: () => uni.showToast({ title: '复制失败，请重试', icon: 'none' }),
    })
    return
  }

  // none：无真实导出路径（仅 base64 无 URL / 无内容），诚实告知，不假装。
  uni.showToast({ title: '当前结果暂无可导出内容', icon: 'none' })
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
.result-template { font-size: 22rpx; color: #8e8e93; margin: 8rpx 0 16rpx; display: block; }
.status-bar { border-radius: 12rpx; padding: 16rpx 20rpx; margin-bottom: 16rpx; display: flex; flex-direction: column; gap: 6rpx; }
.status-bar--core { background: #e8f8ee; border: 1rpx solid #a6e3bf; }
.status-bar--preview { background: #fff4e6; border: 1rpx solid #ffd591; }
.status-badge { font-size: 26rpx; font-weight: 600; color: #1d1d1f; }
.status-line { font-size: 22rpx; color: #555; }
.boundary-note { font-size: 22rpx; color: #ad6800; display: block; margin-bottom: 12rpx; line-height: 1.5; }
.boundary-note--muted { color: #8e8e93; }
.preview-banner { background: #fff1f0; border: 1rpx solid #ffa39e; border-radius: 12rpx; padding: 16rpx 20rpx; margin-bottom: 16rpx; }
.preview-banner-title { font-size: 26rpx; font-weight: 600; color: #cf1322; display: block; }
.preview-banner-text { font-size: 22rpx; color: #a8071a; display: block; margin-top: 6rpx; line-height: 1.5; }
.growth-loop { background: #f0f5ff; border: 1rpx solid #adc6ff; border-radius: 12rpx; padding: 20rpx; margin-bottom: 20rpx; }
.growth-loop-title { font-size: 26rpx; font-weight: 600; color: #1d39c4; display: block; margin-bottom: 12rpx; }
.gl-row { display: flex; justify-content: space-between; gap: 16rpx; padding: 5rpx 0; }
.gl-key { font-size: 22rpx; color: #61616b; flex-shrink: 0; }
.gl-val { font-size: 22rpx; color: #1d1d1f; text-align: right; flex: 1; }
.gl-val--real { color: #237804; font-weight: 600; }
.gl-val--preview { color: #d46b08; font-weight: 600; }
.gl-note { font-size: 20rpx; color: #8e8e93; display: block; margin-top: 10rpx; line-height: 1.5; }
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
.btn-export { background: #1d39c4; color: #fff; border: none; border-radius: 12rpx; font-size: 28rpx; }
.export-hint { font-size: 22rpx; color: #8e8e93; text-align: center; }
.unlocked-tag { font-size: 26rpx; color: #07c160; text-align: center; }
.unlock-hint { font-size: 22rpx; color: #8e8e93; display: block; margin-top: 16rpx; }
.footer { display: flex; gap: 16rpx; margin-top: 32rpx; }
.btn-regen { flex: 1; background: #0071e3; color: #fff; border: none; border-radius: 12rpx; font-size: 28rpx; }
.btn-home { flex: 1; background: #f5f5f7; color: #333; border: 1rpx solid #d1d1d6; border-radius: 12rpx; font-size: 28rpx; }
.empty { padding: 80rpx 32rpx; text-align: center; color: #8e8e93; }
</style>
