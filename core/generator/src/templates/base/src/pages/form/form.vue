<!--
  Blueprint-driven 表单页（单一事实源 = blueprint.json.input_fields）。
  __APP_FEATURE_TITLE__ 由两个生成消费方（core/generator/codegen.py + Node page-builder）
  通过共享 token 契约替换。结构在模板里，数据在 Python，勿在 Python 重写本标记。

  交互闭环：读 loadBlueprint().input_fields 动态渲染（text/textarea/select/image）->
  收集输入 -> mockGenerate({ text, assetPlaceholder, extra }) -> 跳 result 页带 id。

  口径：
  - 主输入（prompt/text）取第一个 text/textarea 字段（必填优先）。
  - 其余字段（select / 额外 textarea 等）进入 extra[字段id]，供 callRealApi 透传后端。
  - image 字段若 drives_generation=false：仅作占位（不参与生成），只传 assetPlaceholder，
    绝不把图片当真实生成输入；页面显式标注「占位 / 不参与生成」。
-->
<template>
  <view class="container">
    <view class="form-card">
      <text class="form-title">__APP_FEATURE_TITLE__</text>

      <view v-for="(f, i) in fields" :key="f.id || i" class="field">
        <text class="field-label">{{ f.label }}<text v-if="f.required" class="req">*</text></text>

        <!-- 占位型 image：仅占位、不参与生成 -->
        <block v-if="f.type === 'image'">
          <view class="asset-slot" @click="pickAsset(f)">
            <text class="asset-tip">{{ assetPicked[f.id] ? '已选择素材（占位，不参与生成）' : (f.placeholder || '点击上传素材（占位，可选）') }}</text>
          </view>
          <text v-if="isPlaceholderImage(f)" class="field-hint">该图片仅作占位，不参与生成；当前按文字输入生成。</text>
        </block>

        <!-- 下拉选择：渲染 options，值写入 extra -->
        <block v-else-if="f.type === 'select'">
          <picker
            class="picker"
            mode="selector"
            :range="f.options || []"
            @change="onSelect(f, $event)"
          >
            <view class="picker-box">
              <text class="picker-text">{{ selected[f.id] || f.placeholder || '请选择' }}</text>
            </view>
          </picker>
        </block>

        <!-- 多行文本 -->
        <textarea
          v-else-if="f.type === 'textarea'"
          class="input-area"
          :placeholder="f.placeholder || '请输入内容 / 主题 / 一句话...'"
          :value="values[f.id]"
          @input="onInput(f, $event)"
        />

        <!-- 单行文本（默认） -->
        <input
          v-else
          class="input-line"
          :placeholder="f.placeholder || '请输入'"
          :value="values[f.id]"
          @input="onInput(f, $event)"
        />
      </view>

      <button class="btn-submit" @click="handleSubmit" :loading="loading" :disabled="loading">
        {{ loading ? '正在生成...' : '开始生成' }}
      </button>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { mockGenerate, loadBlueprint, buildGenerateInput } from '../../services/generation'

const bp = loadBlueprint()
// 没有 input_fields 时退回一个通用文本字段，保证表单始终可用。
const fields = computed<any[]>(() =>
  (bp.input_fields && bp.input_fields.length)
    ? bp.input_fields
    : [{ id: 'text', label: '输入内容', type: 'textarea', required: false, placeholder: '请输入内容 / 主题 / 一句话...' }],
)

const values = reactive<Record<string, string>>({})
const selected = reactive<Record<string, string>>({})
const assetPicked = reactive<Record<string, boolean>>({})
const loading = ref(false)

// image 字段是否仅占位（drives_generation === false）。
function isPlaceholderImage(f: any): boolean {
  return f.type === 'image' && f.drives_generation === false
}

function onInput(f: any, e: any) {
  values[f.id] = (e && e.detail && e.detail.value) || ''
}
function onSelect(f: any, e: any) {
  const idx = Number((e && e.detail && e.detail.value) || 0)
  const opts = f.options || []
  selected[f.id] = opts[idx] != null ? String(opts[idx]) : ''
}
function pickAsset(f: any) {
  // 占位图：只有在 chooseImage success 回调里才标记已选；取消选择不标记。
  // 不读取/上传真实图片内容（不参与生成）。
  uni.chooseImage({
    count: 1,
    success: () => {
      assetPicked[f.id] = true
      uni.showToast({ title: '素材占位已选（不参与生成）', icon: 'none' })
    },
  } as any)
}

async function handleSubmit() {
  // 归一逻辑抽到 generation.ts 的纯函数 buildGenerateInput（可单测）。
  const built = buildGenerateInput(fields.value, values, selected, assetPicked)
  // 必填项缺失：优先提示「请填写必填项」（占位图不参与 valid 判断）。
  if (!built.valid) {
    const msg = built.missingRequired.length ? '请填写必填项' : '请输入内容'
    uni.showToast({ title: msg, icon: 'none' })
    return
  }
  loading.value = true
  try {
    const result = await mockGenerate({
      text: built.text,
      assetPlaceholder: built.assetPlaceholder,
      extra: built.extra,
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
.field { margin-bottom: 24rpx; }
.field-label { font-size: 26rpx; color: #333; display: block; margin-bottom: 10rpx; }
.req { color: #fa5151; margin-left: 6rpx; }
.field-hint { font-size: 22rpx; color: #8e8e93; display: block; margin-top: 8rpx; line-height: 1.5; }
.asset-slot { border: 1rpx dashed #c7c7cc; border-radius: 12rpx; padding: 40rpx; text-align: center; }
.asset-tip { font-size: 26rpx; color: #8e8e93; }
.picker-box { border: 1rpx solid #e8e8ed; border-radius: 12rpx; padding: 22rpx 20rpx; }
.picker-text { font-size: 28rpx; color: #333; }
.input-area { width: 100%; min-height: 200rpx; padding: 20rpx; border: 1rpx solid #e8e8ed; border-radius: 12rpx; font-size: 28rpx; }
.input-line { width: 100%; padding: 22rpx 20rpx; border: 1rpx solid #e8e8ed; border-radius: 12rpx; font-size: 28rpx; }
.btn-submit { margin-top: 16rpx; background: #0071e3; color: #fff; border: none; border-radius: 12rpx; font-size: 30rpx; }
</style>
