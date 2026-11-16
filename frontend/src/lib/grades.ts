export type GradeParts = {
  score?: string
  percentage?: string
  letter?: string
}

type GradeSource = {
  grade?: string | null
  score?: string | null
  percentage?: string | null
  letter_grade?: string | null
  notes?: string | null
}

function clean(value?: string | null): string {
  return (value || '').trim()
}

function formatScore(value: string): string {
  return value.replace(/\s*\/\s*/g, '/')
}

function formatPercentage(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  return /%$/.test(trimmed) ? trimmed : `${trimmed}%`
}

function parseScore(value: string): string | undefined {
  const match = value.match(/\b(\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?)\b/)
  return match ? formatScore(match[1]) : undefined
}

function parsePercentage(value: string): string | undefined {
  const match = value.match(/\b(\d+(?:\.\d+)?)\s*%/)
  if (match) return formatPercentage(match[1])
  if (/^\d+(?:\.\d+)?$/.test(value.trim())) return formatPercentage(value.trim())
  return undefined
}

function parseLetter(value: string): string | undefined {
  const trimmed = value.trim()
  if (/^(?:[A-Fa-f][+-]?|pass|fail|p|f|incomplete|inc)$/i.test(trimmed)) return trimmed
  const composite = trimmed.match(/(?:^|\s·\s*)([A-Fa-f][+-]?)$/)
  return composite ? composite[1] : undefined
}

/** Return the recorded grade in raw-score, percentage, letter order. */
export function gradeParts(source: GradeSource): GradeParts {
  const parts: GradeParts = {}
  if (clean(source.score)) parts.score = formatScore(clean(source.score))
  if (clean(source.percentage)) parts.percentage = formatPercentage(clean(source.percentage))
  if (clean(source.letter_grade)) parts.letter = clean(source.letter_grade)

  const legacy = clean(source.grade)
  if (legacy) {
    const legacyScore = parseScore(legacy)
    const legacyPercentage = parsePercentage(legacy)
    const legacyLetter = parseLetter(legacy)
    if (!parts.score && legacyScore) parts.score = legacyScore
    if (!parts.percentage && legacyPercentage) parts.percentage = legacyPercentage
    if (!parts.letter && legacyLetter) parts.letter = legacyLetter
    if (!legacyScore && !legacyPercentage && !legacyLetter && !parts.score && !parts.percentage && !parts.letter) {
      parts.letter = legacy
    }
  }

  const notes = clean(source.notes)
  if (notes && (!parts.score || !parts.percentage)) {
    const noteScore = parseScore(notes)
    const notePercentage = parsePercentage(notes)
    if (!parts.score && noteScore) parts.score = noteScore
    if (!parts.percentage && notePercentage) parts.percentage = notePercentage
  }

  return parts
}

export function gradePartsList(source: GradeSource): string[] {
  const parts = gradeParts(source)
  return [parts.score, parts.percentage, parts.letter].filter((value): value is string => Boolean(value))
}

export function composeGrade(parts: GradeParts): string {
  return [parts.score, parts.percentage, parts.letter].filter(Boolean).join(' · ')
}
