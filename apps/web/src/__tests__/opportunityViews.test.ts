// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import OpportunityBoard from '../components/OpportunityBoard.vue'
import OpportunityExplorer from '../components/OpportunityExplorer.vue'

describe('OpportunityBoard', () => {
  it('emits launch option updates from presets and opens the requested view', async () => {
    const wrapper = mount(OpportunityBoard, {
      props: {
        summary: {
          exists: true,
          dedup_stats: { unique_apps: 18 },
          feature_stats: { recommended_features: 26 },
          queue_stats: { pending: 9 },
          top_queue: [],
          top_candidates: [],
          top_features: [],
          top_templates: {},
        },
        currentJob: null,
        running: false,
        mode: 'auto',
        launchOptions: {
          regions: 'CN,US',
          platforms: 'app_store',
          limit: 10,
          max_generate: 1,
        },
      },
    })

    await wrapper.get('[data-testid="preset-global"]').trigger('click')
    expect(wrapper.emitted('update-launch-options')?.[0]?.[0]).toEqual({
      regions: 'CN,US,JP,BR',
      platforms: 'app_store,google_play',
      limit: 24,
      max_generate: 3,
    })

    await wrapper.get('[data-testid="features-card"]').trigger('click')
    expect(wrapper.emitted('open-view')?.[0]).toEqual(['features'])
  })
})

describe('OpportunityExplorer', () => {
  it('switches dataset tabs and filters feature cards by template', async () => {
    const wrapper = mount(OpportunityExplorer, {
      props: {
        selectedView: 'features',
        queue: [],
        candidates: [],
        features: [
          {
            feature_key: 'avatar',
            feature_name_cn: 'AI 头像',
            parent_app_name: 'CapCut',
            selected_template: 'avatar-viral',
            final_score: 88,
            required_capabilities: ['image_generation'],
            production_recommended: true,
          },
          {
            feature_key: 'subtitle',
            feature_name_cn: 'AI 字幕',
            parent_app_name: 'CapCut',
            selected_template: 'ai-tool',
            final_score: 42,
            required_capabilities: ['video_render'],
            production_recommended: false,
          },
        ],
      },
    })

    expect(wrapper.text()).toContain('AI 头像')
    await wrapper.get('[data-testid="tab-candidates"]').trigger('click')
    expect(wrapper.emitted('update:selectedView')?.[0]).toEqual(['candidates'])

    const avatarFilter = wrapper.findAll('.filter-chip').find((node) => node.text().includes('avatar-viral'))
    expect(avatarFilter).toBeTruthy()
    await avatarFilter!.trigger('click')
    expect(wrapper.text()).toContain('AI 头像')
    expect(wrapper.text()).not.toContain('AI 字幕')
  })
})
