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

function health() {
  return {
    total: 4, pending: 1, running: 1, succeeded: 1, failed: 1, cancelled: 0,
    oldest_pending_seconds: 125, running_count: 1, active_worker_count: 2,
  }
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

  it('renders queue health line when health provided', () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '', health: health() },
    })
    const line = wrapper.find('[data-testid="queue-health"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('2')      // active_worker_count
    expect(line.text()).toContain('125')    // oldest_pending_seconds
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

  it('defaults to showing all tasks with the total tile selected', () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    expect(wrapper.findAll('.task-row').length).toBe(2)
    expect(wrapper.find('.summary-tile--total').classes()).toContain('summary-tile--selected')
  })

  it('filters the task list to a single status when its tile is clicked', async () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    // 点「已失败」卡片，只剩 failed 任务
    await wrapper.get('.summary-tile--failed').trigger('click')
    const rows = wrapper.findAll('.task-row')
    expect(rows.length).toBe(1)
    expect(wrapper.text()).toContain('build failed') // 仅剩的 failed 任务
    expect(wrapper.find('.summary-tile--failed').classes()).toContain('summary-tile--selected')
  })

  it('shows a filtered-empty state when a status has no matching tasks', async () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    // 没有 cancelled 任务，点它应显示「筛选下无任务」而非「还没有任务」
    await wrapper.get('.summary-tile--cancelled').trigger('click')
    expect(wrapper.find('[data-testid="task-empty-filtered"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="task-empty"]').exists()).toBe(false)
  })

  it('returns to all tasks when the total tile is clicked again', async () => {
    const wrapper = mount(TaskQueuePanel, {
      props: { summary: summary(), tasks: tasks(), busyTaskId: '' },
    })
    await wrapper.get('.summary-tile--failed').trigger('click')
    expect(wrapper.findAll('.task-row').length).toBe(1)
    await wrapper.get('.summary-tile--total').trigger('click')
    expect(wrapper.findAll('.task-row').length).toBe(2)
  })
})
