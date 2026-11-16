import { describe, expect, it } from 'vitest'
import { composeGrade, gradeParts, gradePartsList } from './grades'

describe('gradeParts', () => {
  it('keeps structured score, percentage, and letter in order', () => {
    const parts = gradeParts({ score: '54/60', percentage: '90%', letter_grade: 'A+' })
    expect(gradePartsList({ score: '54/60', percentage: '90%', letter_grade: 'A+' })).toEqual(['54/60', '90%', 'A+'])
    expect(composeGrade(parts)).toBe('54/60 · 90% · A+')
  })

  it('normalizes legacy percentages and bare numbers', () => {
    expect(gradeParts({ grade: '100%' })).toEqual({ percentage: '100%' })
    expect(gradeParts({ grade: '100' })).toEqual({ percentage: '100%' })
  })

  it('recognizes a raw score and a letter grade', () => {
    expect(gradeParts({ grade: '54/60' })).toEqual({ score: '54/60' })
    expect(gradeParts({ grade: 'A+' })).toEqual({ letter: 'A+' })
  })

  it('recovers the score and percentage from a structured note', () => {
    expect(gradeParts({
      grade: 'A+',
      notes: 'Student reported score: 54/60 (90%, A+), equivalent to 27/30 percentage points.',
    })).toEqual({ score: '54/60', percentage: '90%', letter: 'A+' })
  })

  it('does not invent components that are not recorded', () => {
    expect(gradeParts({})).toEqual({})
    expect(gradeParts({ grade: 'Pass' })).toEqual({ letter: 'Pass' })
  })
})
