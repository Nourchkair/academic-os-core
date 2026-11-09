import type { Task } from '../types'

export type TaskUrgency = 'completed' | 'overdue' | 'urgent' | 'soon' | 'upcoming' | 'unscheduled'

export function getTaskUrgency(task: Pick<Task, 'completed' | 'due_date'>, timezone: string, now = new Date()): TaskUrgency {
  if (task.completed) return 'completed'
  if (!task.due_date) return 'unscheduled'

  const today = localDate(now, timezone)
  const dueDate = task.due_date.slice(0, 10)
  const daysUntil = Math.round((Date.parse(`${dueDate}T12:00:00Z`) - Date.parse(`${today}T12:00:00Z`)) / 86_400_000)
  if (daysUntil < 0) return 'overdue'
  if (daysUntil <= 1) return 'urgent'
  if (daysUntil <= 7) return 'soon'
  return 'upcoming'
}

export function urgencyLabel(urgency: TaskUrgency): string {
  switch (urgency) {
    case 'completed': return 'Completed'
    case 'overdue': return 'Past due'
    case 'urgent': return 'Due very soon'
    case 'soon': return 'Due soon'
    case 'upcoming': return 'Upcoming'
    case 'unscheduled': return 'Date to confirm'
  }
}

function localDate(date: Date, timezone: string) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
