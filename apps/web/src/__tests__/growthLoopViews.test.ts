// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import FactoryConsole from '../components/FactoryConsole.vue'
import DecisionOverview from '../components/DecisionOverview.vue'
import DeliverablesPanel from '../components/DeliverablesPanel.vue'
import { api } from '../services/api'
import type { JobDetail } from '../types/job'

// 一个核心模板（avatar-viral）真实接入传播闭环的 job：generator-source + growth-qa 都到位。
function coreJob(): JobDetail {
  return {
    id: 'job-core-0001',
    path: '/tmp/job',
    artifacts: {
      'generator-source.json': {
        preview_type: 'avatar',
        template_status: 'core_runnable',
        real_generation: true,
        fallback_mode: false,
        growth_loop: {
          share_title: '我生成了专属 AI 头像',
          share_copy: '看看哪张最像我，分享后解锁高清无水印头像',
          unlock_hint: '分享给好友后解锁高清无水印头像和更多风格',
          has_watermark: true,
          remove_watermark_supported: true,
          export_supported: true,
          export_label: '下载高清头像',
          capability_mode: 'real',
        },
        growth_loop_summary: {
          growth_loop_present: true,
          has_share_cta: true,
          has_unlock: true,
          has_watermark: true,
          remove_watermark_supported: true,
          brand_exposure: true,
          export_supported: true,
          capability_mode: 'real',
        },
      },
      'growth-qa-report.json': {
        passed: true,
        checks: {
          growth_loop_in_blueprint: true,
          generation_consumes_growth_loop: true,
          result_displays_growth_loop: true,
          result_displays_share_cta: true,
          result_displays_unlock: true,
          result_displays_watermark: true,
          result_displays_remove_watermark: true,
          result_displays_brand: true,
          result_displays_export: true,
          capability_mode_visible: true,
          core_template_not_downgraded: true,
        },
      },
    },
    miniapp_path: '/tmp/job/generated/miniapp',
  }
}

// 视频边界型（fallback_preview）job。
function previewJob(): JobDetail {
  return {
    id: 'job-preview-0002',
    path: '/tmp/job2',
    artifacts: {
      'generator-source.json': {
        preview_type: 'funnyStoryboard',
        template_status: 'honest_preview',
        real_generation: false,
        fallback_mode: true,
        growth_loop: {
          share_title: '这个搞笑分镜我能笑一年',
          share_copy: '当前为分镜脚本预览，分享后解锁更多脚本模板',
          unlock_hint: '分享预览脚本后解锁更多分镜模板',
          has_watermark: true,
          remove_watermark_supported: true,
          export_supported: true,
          export_label: '导出脚本预览',
          capability_mode: 'fallback_preview',
        },
        growth_loop_summary: {
          growth_loop_present: true,
          has_share_cta: true,
          has_unlock: true,
          has_watermark: true,
          remove_watermark_supported: true,
          brand_exposure: true,
          export_supported: true,
          capability_mode: 'fallback_preview',
        },
      },
    },
  }
}

describe('FactoryConsole growth loop status', () => {
  it('shows share / unlock / watermark / remove-watermark / brand / export / capability', () => {
    const wrapper = mount(FactoryConsole, {
      props: {
        job: coreJob(),
        running: false,
        logs: [],
        runtimePipelineSteps: [],
        selectedStepId: '',
      },
    })
    expect(wrapper.find('[data-testid="gl-share"]').text()).toContain('有')
    expect(wrapper.find('[data-testid="gl-unlock"]').text()).toContain('有')
    expect(wrapper.find('[data-testid="gl-watermark"]').text()).toContain('有')
    expect(wrapper.find('[data-testid="gl-remove-watermark"]').text()).toContain('支持')
    expect(wrapper.find('[data-testid="gl-brand"]').text()).toContain('有')
    expect(wrapper.find('[data-testid="gl-export"]').text()).toContain('支持')
    expect(wrapper.find('[data-testid="gl-capability"]').text()).toContain('real')
  })

  it('shows fallback_preview capability for video preview templates', () => {
    const wrapper = mount(FactoryConsole, {
      props: {
        job: previewJob(),
        running: false,
        logs: [],
        runtimePipelineSteps: [],
        selectedStepId: '',
      },
    })
    expect(wrapper.find('[data-testid="gl-capability"]').text()).toContain('fallback_preview')
  })
})

describe('DecisionOverview growth loop impact card', () => {
  it('renders share title / unlock / capability for a real core template', () => {
    const wrapper = mount(DecisionOverview, { props: { job: coreJob() } })
    const card = wrapper.find('[data-testid="growth-loop-card"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('我生成了专属 AI 头像')
    expect(card.text()).toContain('分享给好友后解锁')
    expect(card.text()).toContain('real')
    // 真实模式不显示预览警告
    expect(card.text()).not.toContain('非真实视频生成')
  })

  it('shows preview-mode warning for fallback_preview templates', () => {
    const wrapper = mount(DecisionOverview, { props: { job: previewJob() } })
    const card = wrapper.find('[data-testid="growth-loop-card"]')
    expect(card.text()).toContain('fallback_preview')
    expect(card.text()).toContain('非真实视频生成')
  })
})

describe('DeliverablesPanel propagation productization', () => {
  it('marks fully wired growth loop as 产品层已接入', () => {
    const wrapper = mount(DeliverablesPanel, { props: { job: coreJob() } })
    const status = wrapper.find('[data-testid="propagation-status"]')
    expect(status.exists()).toBe(true)
    expect(status.text()).toContain('产品层已接入')
  })

  it('每个有内容的交付物卡片都有「下载」按钮，下载会触发浏览器保存', () => {
    const job: JobDetail = {
      id: 'job-dl',
      path: '/tmp/dl',
      artifacts: {
        'candidate.json': { name_cn: '表情包' },
        'prd.md': '# 表情包 小程序 — 产品需求文档',
      },
    }
    const wrapper = mount(DeliverablesPanel, { props: { job } })
    const downloadBtns = wrapper.findAll('.action-btn--download')
    expect(downloadBtns.length).toBeGreaterThanOrEqual(2)

    // 点击下载：应创建带 download 属性的 <a> 并触发 click。
    const created: HTMLAnchorElement[] = []
    const origCreate = document.createElement.bind(document)
    const createSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag) as HTMLAnchorElement
      if (tag === 'a') { el.click = () => {}; created.push(el) }
      return el as any
    })
    ;(URL as any).createObjectURL = vi.fn(() => 'blob:fake')
    ;(URL as any).revokeObjectURL = vi.fn()

    downloadBtns[0].trigger('click')
    expect(created.length).toBe(1)
    expect(created[0].download).toBe('candidate.json')
    createSpy.mockRestore()
  })

  it('小程序源码 / 构建产物 卡片提供「下载 ZIP」按钮，点击调用 zip 接口', async () => {
    const dlSpy = vi.spyOn(api, 'downloadJobZip').mockResolvedValue()
    const job: JobDetail = {
      id: 'job-zip',
      path: '/tmp/zip',
      miniapp_path: '/tmp/zip/generated/miniapp',
      artifacts: {
        'qa-report.json': { checks: { dist_exists: true } },
      },
    }
    const wrapper = mount(DeliverablesPanel, { props: { job } })
    const zipBtns = wrapper.findAll('.action-btn--download').filter((b: any) => b.text().includes('ZIP'))
    expect(zipBtns.length).toBe(2)  // 小程序源码 + 构建产物
    await zipBtns[0].trigger('click')
    expect(dlSpy).toHaveBeenCalledWith('job-zip', 'miniapp')
    dlSpy.mockRestore()
  })

  it('marks doc-only (no growth loop) as 只有文档 / 缺失', () => {
    const docOnly: JobDetail = {
      id: 'job-doc',
      path: '/tmp/doc',
      artifacts: {
        'growth-plan.md': '# 增长计划',
        'share-strategy.md': '# 分享策略',
      },
    }
    const wrapper = mount(DeliverablesPanel, { props: { job: docOnly } })
    const status = wrapper.find('[data-testid="propagation-status"]')
    expect(status.exists()).toBe(true)
    expect(['只有文档', '缺失']).toContain(status.find('.prop-badge').text())
  })

  it('does NOT show 产品层已接入 when result_displays_export is missing (finding #3)', () => {
    const job = coreJob()
    job.artifacts['growth-qa-report.json'].checks.result_displays_export = false
    const wrapper = mount(DeliverablesPanel, { props: { job } })
    const status = wrapper.find('[data-testid="propagation-status"]')
    expect(status.text()).not.toContain('产品层已接入')
    expect(status.find('.prop-badge').text()).toContain('未完全接入')
  })

  it('does NOT show 产品层已接入 when result_displays_brand is missing (finding #3)', () => {
    const job = coreJob()
    job.artifacts['growth-qa-report.json'].checks.result_displays_brand = false
    const wrapper = mount(DeliverablesPanel, { props: { job } })
    const status = wrapper.find('[data-testid="propagation-status"]')
    expect(status.text()).not.toContain('产品层已接入')
  })

  it('does NOT show 产品层已接入 when core template is downgraded (finding #3)', () => {
    const job = coreJob()
    job.artifacts['growth-qa-report.json'].checks.core_template_not_downgraded = false
    const wrapper = mount(DeliverablesPanel, { props: { job } })
    const status = wrapper.find('[data-testid="propagation-status"]')
    expect(status.text()).not.toContain('产品层已接入')
  })

  it('shows 待 QA 验证 when only generator-source summary exists (no growth-qa-report)', () => {
    const summaryOnly: JobDetail = {
      id: 'job-summary',
      path: '/tmp/summary',
      artifacts: {
        'generator-source.json': {
          growth_loop_summary: {
            growth_loop_present: true,
            has_share_cta: true,
            has_unlock: true,
            has_watermark: true,
            remove_watermark_supported: true,
            brand_exposure: true,
            export_supported: true,
            capability_mode: 'real',
          },
        },
      },
    }
    const wrapper = mount(DeliverablesPanel, { props: { job: summaryOnly } })
    const status = wrapper.find('[data-testid="propagation-status"]')
    expect(status.text()).not.toContain('产品层已接入')
    expect(status.find('.prop-badge').text()).toContain('待 QA 验证')
  })
})

// --- P0-2 finding #6：mock 构建下 dashboard 读 effective summary，不显示 real / 高清导出 ---

// mock 构建：模板事实源 real，但 effective 已折算为 fallback_preview + export off。
function mockBuildJob(): JobDetail {
  return {
    id: 'job-mock-0003',
    path: '/tmp/job3',
    artifacts: {
      'generator-source.json': {
        preview_type: 'avatar',
        template_status: 'core_runnable',
        real_generation: true,
        fallback_mode: false,
        generation_mode: 'mock',
        // 模板事实源摘要：real（区分清楚）。
        template_growth_loop_summary: {
          growth_loop_present: true, has_share_cta: true, has_unlock: true,
          has_watermark: true, remove_watermark_supported: true, brand_exposure: true,
          export_supported: true, capability_mode: 'real',
        },
        growth_loop_summary: {
          growth_loop_present: true, has_share_cta: true, has_unlock: true,
          has_watermark: true, remove_watermark_supported: true, brand_exposure: true,
          export_supported: true, capability_mode: 'real',
        },
        // 运行时有效摘要：mock 构建 -> fallback_preview + export off。
        effective_growth_loop_summary: {
          growth_loop_present: true, has_share_cta: true, has_unlock: true,
          has_watermark: true, remove_watermark_supported: true, brand_exposure: true,
          export_supported: false, capability_mode: 'fallback_preview',
          effective_note: '当前构建未配置真实生成 API，运行时展示本地预览（非真实高清下载）',
        },
        growth_loop: { capability_mode: 'real', share_title: 't', share_copy: 'c', unlock_hint: 'u' },
      },
    },
  }
}

describe('dashboard effective summary (finding #6: mock build not shown as real)', () => {
  it('FactoryConsole shows preview capability + export 已预留, not real', () => {
    const wrapper = mount(FactoryConsole, {
      props: { job: mockBuildJob(), running: false, logs: [], runtimePipelineSteps: [], selectedStepId: '' },
    })
    const cap = wrapper.find('[data-testid="gl-capability"]')
    expect(cap.text()).toContain('fallback_preview')
    expect(cap.text()).not.toContain('real · 真实生成')
    // 导出摘要显示「已预留」（effective export off），不显示「支持」。
    expect(wrapper.find('[data-testid="gl-export"]').text()).toContain('已预留')
  })

  it('DecisionOverview marks preview mode for mock build even though template is real', () => {
    const wrapper = mount(DecisionOverview, { props: { job: mockBuildJob() } })
    const card = wrapper.find('[data-testid="growth-loop-card"]')
    expect(card.text()).toContain('fallback_preview')
  })

  it('api build keeps real (control case)', () => {
    const job = mockBuildJob()
    job.artifacts['generator-source.json'].generation_mode = 'api'
    job.artifacts['generator-source.json'].effective_growth_loop_summary = {
      growth_loop_present: true, has_share_cta: true, has_unlock: true,
      has_watermark: true, remove_watermark_supported: true, brand_exposure: true,
      export_supported: true, capability_mode: 'real', effective_note: '',
    }
    const wrapper = mount(FactoryConsole, {
      props: { job, running: false, logs: [], runtimePipelineSteps: [], selectedStepId: '' },
    })
    expect(wrapper.find('[data-testid="gl-capability"]').text()).toContain('real · 真实生成')
  })
})

// --- P0-2 商业闭环卡片（DeliverablesPanel commercial-loop）---

// mock 构建 + 核心模板（avatar）：广告门槛未生效、仅本地预览、不可高清下载。
function commercialMockJob(): JobDetail {
  return {
    id: 'job-comm-mock',
    path: '/tmp/cm',
    artifacts: {
      'generator-source.json': {
        generation_mode: 'mock',
        real_generation: true,
        rewarded_ad_enabled: false,
        template_growth_loop_summary: {
          growth_loop_present: true, capability_mode: 'real', export_supported: true,
          download_gate_type: 'rewarded_ad', download_gate_required_for: ['download', 'remove_watermark'],
        },
        effective_growth_loop_summary: {
          growth_loop_present: true, capability_mode: 'fallback_preview', export_supported: false,
          effective_note: '当前构建未配置真实生成 API，运行时展示本地预览（非真实高清下载）',
        },
      },
    },
  }
}

// api 构建 + 广告已配置：激励广告已配置、高清下载需完播广告。
function commercialApiJob(): JobDetail {
  return {
    id: 'job-comm-api',
    path: '/tmp/ca',
    artifacts: {
      'generator-source.json': {
        generation_mode: 'api',
        real_generation: true,
        rewarded_ad_enabled: true,
        template_growth_loop_summary: {
          growth_loop_present: true, capability_mode: 'real', export_supported: true,
          download_gate_type: 'rewarded_ad', download_gate_required_for: ['download', 'remove_watermark'],
        },
        effective_growth_loop_summary: {
          growth_loop_present: true, capability_mode: 'real', export_supported: true, effective_note: '',
        },
      },
    },
  }
}

// funny 视频边界型：导出预览脚本，不下载视频。
function commercialFunnyJob(): JobDetail {
  return {
    id: 'job-comm-funny',
    path: '/tmp/cf',
    artifacts: {
      'generator-source.json': {
        generation_mode: 'api',
        real_generation: false,
        rewarded_ad_enabled: true,
        template_growth_loop_summary: {
          growth_loop_present: true, capability_mode: 'fallback_preview', export_supported: true,
          download_gate_type: 'rewarded_ad', download_gate_required_for: ['export'],
        },
        effective_growth_loop_summary: {
          growth_loop_present: true, capability_mode: 'fallback_preview', export_supported: true, effective_note: '',
        },
      },
    },
  }
}

describe('DeliverablesPanel commercial-loop card (P0-2)', () => {
  it('mock build core template: 广告门槛未配置 + 本地预览 + 不可高清下载 + 风险提示', () => {
    const wrapper = mount(DeliverablesPanel, { props: { job: commercialMockJob() } })
    const card = wrapper.find('[data-testid="commercial-loop"]')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('未配置')
    expect(card.text()).toContain('本地预览')
    expect(card.text()).toContain('不可变现')
    expect(card.text()).toContain('mock 构建')
  })

  it('api build + ad configured: 激励广告已配置 + 图片/视频/文本下载', () => {
    const wrapper = mount(DeliverablesPanel, { props: { job: commercialApiJob() } })
    const card = wrapper.find('[data-testid="commercial-loop"]')
    expect(card.text()).toContain('已配置')
    expect(card.text()).toContain('激励广告')
    expect(card.text()).toContain('图片 / 视频 / 文本')
  })

  it('funny/blessing: 导出预览, NOT 下载视频', () => {
    const wrapper = mount(DeliverablesPanel, { props: { job: commercialFunnyJob() } })
    const card = wrapper.find('[data-testid="commercial-loop"]')
    expect(card.text()).toContain('文本预览导出')
    expect(card.text()).not.toContain('下载视频')
    expect(card.text()).toContain('只导出脚本/卡片预览')
  })

  it('FactoryConsole shows 广告门槛 已配置 for api+ad job', () => {
    const wrapper = mount(FactoryConsole, {
      props: { job: commercialApiJob(), running: false, logs: [], runtimePipelineSteps: [], selectedStepId: '' },
    })
    expect(wrapper.find('[data-testid="gl-ad-gate"]').text()).toContain('已配置')
  })

  it('FactoryConsole shows 广告门槛 未配置 for mock job', () => {
    const wrapper = mount(FactoryConsole, {
      props: { job: commercialMockJob(), running: false, logs: [], runtimePipelineSteps: [], selectedStepId: '' },
    })
    expect(wrapper.find('[data-testid="gl-ad-gate"]').text()).toContain('未配置')
  })
})
