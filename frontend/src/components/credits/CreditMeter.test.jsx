import React from 'react'
import { renderToString } from 'react-dom/server'
import { describe, it, expect } from 'vitest'
import { CreditMeter, CreditProgressWidget } from './CreditMeter'

describe('Credit Usage Meter Component (FE-20)', () => {
  describe('Threshold & Status Behavior', () => {
    it('1. Usage below 80% displays normal styling', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={50}
          budget={100}
        />
      )

      expect(html).toContain('50%')
      expect(html).toContain('>Normal<')
      expect(html).toContain('var(--color-score-high, #15803d)')
      expect(html).not.toContain('>Warning<')
      expect(html).not.toContain('>Danger<')
      expect(html).not.toContain('Budget exceeded')
    })

    it('2. Usage at exactly 80% displays warning styling', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={80}
          budget={100}
        />
      )

      expect(html).toContain('80%')
      expect(html).toContain('>Warning<')
      expect(html).toContain('var(--color-score-medium, #b45309)')
      expect(html).toContain('Warning: High usage')
      expect(html).not.toContain('>Normal<')
      expect(html).not.toContain('>Danger<')
    })

    it('3. Usage immediately below 80% (79.99%) displays normal styling', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={79.99}
          budget={100}
        />
      )

      expect(html).toContain('79.99%')
      expect(html).toContain('>Normal<')
      expect(html).toContain('var(--color-score-high, #15803d)')
      expect(html).not.toContain('>Warning<')
      expect(html).not.toContain('>Danger<')
      expect(html).not.toContain('Warning: High usage')
    })

    it('4. Usage immediately above 80% (80.01%) displays warning styling', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={80.01}
          budget={100}
        />
      )

      expect(html).toContain('80.01%')
      expect(html).toContain('>Warning<')
      expect(html).toContain('var(--color-score-medium, #b45309)')
      expect(html).toContain('Warning: High usage')
      expect(html).not.toContain('>Normal<')
      expect(html).not.toContain('>Danger<')
    })

    it('Boundary test suite: strict evaluation of 79.99%, 80%, and 80.01%', () => {
      const below = renderToString(
        <CreditProgressWidget
          title="Test"
          ariaLabel="Test"
          used={79.99}
          budget={100}
        />
      )
      const exact = renderToString(
        <CreditProgressWidget
          title="Test"
          ariaLabel="Test"
          used={80}
          budget={100}
        />
      )
      const above = renderToString(
        <CreditProgressWidget
          title="Test"
          ariaLabel="Test"
          used={80.01}
          budget={100}
        />
      )

      // 79.99% must be normal, not rounded to 80% warning
      expect(below).toContain('>Normal<')
      expect(below).toContain('79.99%')
      expect(below).not.toContain('>Warning<')

      // 80% must be warning
      expect(exact).toContain('>Warning<')
      expect(exact).toContain('80%')

      // 80.01% must be warning
      expect(above).toContain('>Warning<')
      expect(above).toContain('80.01%')
    })

    it('5. Usage at 99% displays warning styling', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Monthly Credit Usage"
          ariaLabel="Monthly credit usage"
          used={99}
          budget={100}
        />
      )

      expect(html).toContain('99%')
      expect(html).toContain('>Warning<')
      expect(html).toContain('var(--color-score-medium, #b45309)')
      expect(html).not.toContain('>Danger<')
      expect(html).not.toContain('Budget exceeded')
    })

    it('6. Usage at exactly 100% displays danger styling and budget exceeded notice', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Monthly Credit Usage"
          ariaLabel="Monthly credit usage"
          used={100}
          budget={100}
        />
      )

      expect(html).toContain('100%')
      expect(html).toContain('>Danger<')
      expect(html).toContain('var(--color-score-low, #b91c1c)')
      expect(html).toContain('Danger: Budget exceeded')
      expect(html).toContain('Budget exceeded')
      expect(html).not.toContain('>Warning<')
      expect(html).not.toContain('>Normal<')
    })

    it('7. Usage above 100% displays danger styling and caps visual bar to 100%', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Monthly Credit Usage"
          ariaLabel="Monthly credit usage"
          used={150}
          budget={100}
        />
      )

      expect(html).toContain('150%')
      expect(html).toContain('>Danger<')
      expect(html).toContain('width:100%')
      expect(html).toContain('aria-valuenow="100"')
      expect(html).toContain('Budget exceeded')
    })
  })

  describe('Budget & Usage Edge Cases', () => {
    it('8. Zero budget does not cause division-by-zero or NaN', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={50}
          budget={0}
        />
      )

      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
      expect(html).toContain('>No budget configured<')
      expect(html).toContain('0%')
      expect(html).toContain('width:0%')
      expect(html).toContain('aria-valuenow="0"')
      expect(html).toContain('aria-valuetext="No budget configured"')
    })

    it('9. Zero usage displays 0% with normal styling', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={0}
          budget={100}
        />
      )

      expect(html).toContain('0%')
      expect(html).toContain('>Normal<')
      expect(html).toContain('width:0%')
      expect(html).toContain('aria-valuenow="0"')
      expect(html).toContain('Remaining:')
      expect(html).toContain('>100<')
      expect(html).toContain('credits')
    })

    it('Handles invalid / negative inputs safely', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Invalid test"
          ariaLabel="Invalid test"
          used={-50}
          budget={-100}
        />
      )

      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
      expect(html).toContain('>No budget configured<')
      expect(html).toContain('0%')
    })
  })

  describe('CreditMeter Container (Daily and Monthly)', () => {
    it('10. Renders both daily and monthly credit usage independently', () => {
      const html = renderToString(
        <CreditMeter
          dailyUsed={30}
          dailyBudget={100}
          monthlyUsed={850}
          monthlyBudget={1000}
        />
      )

      expect(html).toContain('Daily Credit Usage')
      expect(html).toContain('Monthly Credit Usage')

      // Daily is 30% -> Normal
      expect(html).toContain('30%')
      expect(html).toContain('>Normal<')

      // Monthly is 85% -> Warning
      expect(html).toContain('85%')
      expect(html).toContain('>Warning<')
    })

    it('Supports object-style daily and monthly props', () => {
      const html = renderToString(
        <CreditMeter
          credits={{
            daily: { used: 80, budget: 100 },
            monthly: { used: 200, budget: 200 }
          }}
        />
      )

      expect(html).toContain('80%')
      expect(html).toContain('>Warning<')
      expect(html).toContain('100%')
      expect(html).toContain('>Danger<')
    })
  })

  describe('Visual & Accessibility Validation', () => {
    it('11. Progress bar width is clamped between 0% and 100%', () => {
      const normalHtml = renderToString(
        <CreditProgressWidget
          title="Test"
          ariaLabel="Test"
          used={45}
          budget={100}
        />
      )
      expect(normalHtml).toContain('width:45%')

      const overHtml = renderToString(
        <CreditProgressWidget
          title="Test"
          ariaLabel="Test"
          used={250}
          budget={100}
        />
      )
      // Visual width is capped at 100%, while raw percentage can be 250%
      expect(overHtml).toContain('250%')
      expect(overHtml).toContain('width:100%')
      expect(overHtml).not.toContain('width:250%')
    })

    it('12. Exposes all required accessibility attributes and ranges correctly', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={80}
          budget={100}
        />
      )

      expect(html).toContain('role="progressbar"')
      expect(html).toContain('aria-label="Daily credit usage"')
      expect(html).toContain('aria-valuemin="0"')
      expect(html).toContain('aria-valuemax="100"')
      expect(html).toContain('aria-valuenow="80"')
      expect(html).toContain(
        'aria-valuetext="80% (80 of 100 credits used, 20 remaining) - Warning: High usage"'
      )
    })

    it('Maintains accessible value text when budget is exceeded', () => {
      const html = renderToString(
        <CreditProgressWidget
          title="Monthly Credit Usage"
          ariaLabel="Monthly credit usage"
          used={120}
          budget={100}
        />
      )

      expect(html).toContain('aria-valuenow="100"')
      expect(html).toContain(
        'aria-valuetext="120% (120 of 100 credits used, 0 remaining) - Danger: Budget exceeded"'
      )
    })
  })
})
