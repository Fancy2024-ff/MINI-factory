// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskQueuePanel from '../components/TaskQueuePanel.vue'
import type { TaskItem, TaskSummary } from '../types/job'

function summary(): TaskSummary {
  return {
    total: 4,
    by_status: { pending: 1, running: 1, succeeded: 1, failed: 1, cancelled: 0 },
    by_kind: { 'pipeline.run': 4 },
  }
}

function tasks(): TaskItem[] {
  return [
    {
      id: 'task-running-0001', kind: 'pipeline.run', status: 'running',
      priority: 100, attempts: 1, max_attempts: 3,
      queue_id: 'q-001', job_id: 'job-aaaa1111',
    },
    {
      id: 'task-failed-0002', kind: 'pipeline.run', status: 'failed',
      priority: 100, attempts: 3, max_attempts: 3,
      queue_id: 'q-002', error_message: 'pipeline.run exit=1: build failed',
    },
  ]
}

describe('TaskQueuePanel', () => {
  it('renders status summary tiles and the task list', () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    // 全部任务总数
    expect(wrapper.text()).toContain('全部任务')
    expect(wrapper.find('[data-testid="task-list"]').exists()).toBe(true)
    // 队列项映射可见
    expect(wrapper.text()).toContain('q-001')
    expect(wrapper.text()).toContain('build failed')
  })

  it('emits cancel for an active task and retry for a failed task', async () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    const rows = wrapper.findAll('.task-row')
    expect(rows.length).toBe(2)

    // running task -> 取消按钮
    await rows[0].get('.task-btn').trigger('click')
    expect(wrapper.emitted('cancel')?.[0]).toEqual(['task-running-0001'])

    // failed task -> 重试按钮
    await rows[1].get('.task-btn--primary').trigger('click')
    expect(wrapper.emitted('retry')?.[0]).toEqual(['task-failed-0002'])
  })

  it('emits select-job when a job link is clicked', async () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    await wrapper.get('.meta-item--link').trigger('click')
    expect(wrapper.emitted('select-job')?.[0]).toEqual(['job-aaaa1111'])
  })

  it('shows an empty state when there are no tasks', () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: { total: 0, by_status: {}, by_kind: {} }, tasks: [], busyTaskId: '' },
    })
    expect(wrapper.find('[data-testid="task-empty"]').exists()).toBe(true)
  })
})
