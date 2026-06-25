import { describe, it, expect } from 'vitest'
import { validateFeature, type FeatureConfig } from '../tg/registry/featureRegistry'

const base: FeatureConfig = {
  id: 'demo', title: '演示', icon: '🖼', ability: 'text2img',
  task: 'generate_image', subtitle: 's',
  input: { textRequired: true }, params: { promptTemplate: '{input}' },
  ui: { submitLabel: 'go' },
}

describe('validateFeature', () => {
  it('accepts a well-formed text2img feature', () => {
    expect(validateFeature(base).ok).toBe(true)
  })
  it('rejects task not in whitelist', () => {
    expect(validateFeature({ ...base, task: 'restore' as any }).ok).toBe(false)
  })
  it('rejects img2img without imageRequired', () => {
    const f = { ...base, ability: 'img2img' as const, task: 'background_remove' as const,
                input: { imageRequired: false } }
    expect(validateFeature(f).ok).toBe(false)
  })
})
