import React from 'react'

/**
 * Design token status configurations matching tokens.css and WCAG guidelines.
 */
const STATUS_CONFIGS = {
  normal: {
    label: 'Normal',
    color: 'var(--color-score-high, #15803d)',
    bg: 'var(--color-score-high-bg, #dcfce7)',
    barColor: 'var(--color-success, #16a34a)',
    borderColor: 'rgba(21, 128, 61, 0.2)'
  },
  warning: {
    label: 'Warning',
    color: 'var(--color-score-medium, #b45309)',
    bg: 'var(--color-score-medium-bg, #fef3c7)',
    barColor: 'var(--color-warning, #d97706)',
    borderColor: 'rgba(180, 83, 9, 0.2)'
  },
  danger: {
    label: 'Danger',
    color: 'var(--color-score-low, #b91c1c)',
    bg: 'var(--color-score-low-bg, #fee2e2)',
    barColor: 'var(--color-danger, #dc2626)',
    borderColor: 'rgba(185, 28, 28, 0.2)'
  }
}

const NO_BUDGET_CONFIG = {
  label: 'No budget configured',
  color: 'var(--color-text-muted, #64748b)',
  bg: 'var(--color-bg-subtle, #f1f5f9)',
  barColor: 'var(--color-border, #cbd5e1)',
  borderColor: 'var(--color-border, #e2e8f0)'
}

/**
 * Safely sanitizes incoming values to a non-negative finite number.
 * Returns 0 for negative, missing, NaN, or non-finite inputs.
 */
function sanitizeNonNegative(val) {
  if (val === null || val === undefined) return 0
  const num = typeof val === 'number' ? val : Number(val)
  if (!Number.isFinite(num) || Number.isNaN(num) || num < 0) {
    return 0
  }
  return num
}

/**
 * Determines the status level ('normal' | 'warning' | 'danger') based on credit usage percentage.
 * Thresholds:
 *   - percentage >= 100 : danger
 *   - percentage >= 80  : warning
 *   - percentage < 80   : normal
 */
function getUsageStatus(percentage) {
  if (percentage >= 100) {
    return 'danger'
  }

  if (percentage >= 80) {
    return 'warning'
  }

  return 'normal'
}

/**
 * Safely rounds floating point numbers to avoid IEEE-754 precision artifacts.
 */
function roundFloat(num, decimals = 10) {
  if (!Number.isFinite(num)) return 0
  const factor = 10 ** decimals
  return Math.round(num * factor) / factor
}

/**
 * Computes credit usage metrics: percentage, clamping, status, and remaining credits.
 */
function computeUsage(rawUsed, rawBudget) {
  const used = sanitizeNonNegative(rawUsed)
  const budget = sanitizeNonNegative(rawBudget)
  const hasBudget = budget > 0

  let percentage = 0
  if (hasBudget) {
    const rawPct = (used / budget) * 100
    percentage = Number.isFinite(rawPct) ? roundFloat(rawPct, 10) : 0
  }

  // Clamped between 0% and 100% for the visual progress bar and aria-valuenow
  const clampedPercentage = Math.min(100, Math.max(0, percentage))

  // Thresholds:
  // Usage < 80%: Normal
  // Usage >= 80% and < 100%: Warning
  // Usage >= 100%: Danger
  const status = getUsageStatus(percentage)

  // Remaining credits: 0 if no budget or if usage exceeds budget
  const rawRemaining = hasBudget ? Math.max(0, budget - used) : 0
  const remaining = roundFloat(rawRemaining, 10)

  return {
    used,
    budget,
    hasBudget,
    percentage,
    clampedPercentage,
    status,
    remaining
  }
}

/**
 * Single progress widget for credit usage.
 */
export function CreditProgressWidget({
  title,
  ariaLabel,
  used = 0,
  budget = 0,
  style = {}
}) {
  const metrics = computeUsage(used, budget)
  const {
    used: safeUsed,
    budget: safeBudget,
    hasBudget,
    percentage,
    clampedPercentage,
    status,
    remaining
  } = metrics

  const statusConfig = hasBudget ? STATUS_CONFIGS[status] : NO_BUDGET_CONFIG

  const accessibleValueText = hasBudget
    ? `${percentage}% (${safeUsed} of ${safeBudget} credits used, ${remaining} remaining)${
        status === 'danger'
          ? ' - Danger: Budget exceeded'
          : status === 'warning'
            ? ' - Warning: High usage'
            : ''
      }`
    : 'No budget configured'

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        padding: '16px',
        borderRadius: 'var(--radius-md, 8px)',
        backgroundColor: 'var(--color-bg-subtle, #f8fafc)',
        border: '1px solid var(--color-border, #e2e8f0)',
        ...style
      }}
    >
      {/* Header row: Heading and Status Badge */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px'
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: '14px',
            fontWeight: 600,
            color: 'var(--color-text-main, #0f172a)'
          }}
        >
          {title}
        </h3>
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 8px',
            borderRadius: 'var(--radius-full, 9999px)',
            fontSize: '12px',
            fontWeight: 600,
            color: statusConfig.color,
            backgroundColor: statusConfig.bg,
            border: `1px solid ${statusConfig.borderColor}`
          }}
        >
          {hasBudget ? statusConfig.label : 'No budget configured'}
        </span>
      </div>

      {/* Main stats: Percentage and Credits Consumed vs Budget */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '8px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
          <span
            style={{
              fontSize: '24px',
              fontWeight: 700,
              lineHeight: 1,
              color: hasBudget ? statusConfig.color : 'var(--color-text-muted, #64748b)'
            }}
          >
            {percentage}%
          </span>
          <span style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)' }}>
            used
          </span>
        </div>
        <div style={{ fontSize: '13px', color: 'var(--color-text-muted, #64748b)' }}>
          {hasBudget ? (
            <span>
              <strong style={{ color: 'var(--color-text-main, #0f172a)' }}>{safeUsed}</strong> / {safeBudget} credits
            </span>
          ) : (
            <span>
              <strong style={{ color: 'var(--color-text-main, #0f172a)' }}>{safeUsed}</strong> credits used
            </span>
          )}
        </div>
      </div>

      {/* Visual Progress Bar with full ARIA attributes */}
      <div
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={clampedPercentage}
        aria-valuetext={accessibleValueText}
        style={{
          width: '100%',
          height: '8px',
          backgroundColor: 'var(--color-border, #e2e8f0)',
          borderRadius: 'var(--radius-full, 9999px)',
          overflow: 'hidden'
        }}
      >
        <div
          style={{
            width: `${clampedPercentage}%`,
            height: '100%',
            backgroundColor: statusConfig.barColor,
            borderRadius: 'inherit',
            transition: 'width 0.25s ease'
          }}
        />
      </div>

      {/* Footer row: Remaining Credits or Fallback Notice */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontSize: '12px',
          color: 'var(--color-text-muted, #64748b)'
        }}
      >
        {hasBudget ? (
          <>
            <span>
              Remaining:{' '}
              <strong style={{ color: 'var(--color-text-main, #0f172a)' }}>
                {remaining}
              </strong>{' '}
              credits
            </span>
            {status === 'danger' && (
              <span style={{ color: 'var(--color-danger, #dc2626)', fontWeight: 600 }}>
                Budget exceeded
              </span>
            )}
          </>
        ) : (
          <span style={{ color: 'var(--color-text-muted, #64748b)', fontStyle: 'italic' }}>
            No budget configured
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * CreditMeter Component (FE-20).
 * Displays two credit usage progress widgets: Daily Credit Usage and Monthly Credit Usage.
 *
 * Props:
 *  - dailyUsed / dailyCreditsUsed: number (daily credits consumed)
 *  - dailyBudget / dailyCreditBudget: number (daily credit budget)
 *  - monthlyUsed / monthlyCreditsUsed: number (monthly credits consumed)
 *  - monthlyBudget / monthlyCreditBudget: number (monthly credit budget)
 *  - daily: { used, budget } (optional object syntax)
 *  - monthly: { used, budget } (optional object syntax)
 *  - credits: { daily: {...}, monthly: {...} } (optional nested syntax)
 *  - title: string (default: "Credit Usage")
 *  - style: object (inline style overrides)
 *  - className: string (optional CSS classes)
 */
export function CreditMeter({
  dailyUsed,
  dailyBudget,
  monthlyUsed,
  monthlyBudget,
  dailyCreditsUsed,
  dailyCreditBudget,
  monthlyCreditsUsed,
  monthlyCreditBudget,
  daily,
  monthly,
  credits,
  creditsUsed,
  creditBudget,
  title = 'Credit Usage',
  style = {},
  className = '',
  ...restProps
}) {
  // Extract daily values with backward/forward compatibility
  const dailySource = daily || credits?.daily || {}
  const resolvedDailyUsed =
    dailyUsed ??
    dailyCreditsUsed ??
    dailySource.used ??
    dailySource.creditsUsed ??
    dailySource.credits_used ??
    creditsUsed
  const resolvedDailyBudget =
    dailyBudget ??
    dailyCreditBudget ??
    dailySource.budget ??
    dailySource.creditBudget ??
    dailySource.credit_budget ??
    creditBudget

  // Extract monthly values with backward/forward compatibility
  const monthlySource = monthly || credits?.monthly || {}
  const resolvedMonthlyUsed =
    monthlyUsed ??
    monthlyCreditsUsed ??
    monthlySource.used ??
    monthlySource.creditsUsed ??
    monthlySource.credits_used
  const resolvedMonthlyBudget =
    monthlyBudget ??
    monthlyCreditBudget ??
    monthlySource.budget ??
    monthlySource.creditBudget ??
    monthlySource.credit_budget

  return (
    <section
      aria-label={title || 'Credit Usage'}
      className={className}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        backgroundColor: 'var(--color-bg-surface, #ffffff)',
        borderRadius: 'var(--radius-md, 8px)',
        border: '1px solid var(--color-border, #e2e8f0)',
        padding: '20px',
        boxShadow: 'var(--shadow-sm, 0 1px 2px 0 rgb(0 0 0 / 0.05))',
        ...style
      }}
      {...restProps}
    >
      {title ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid var(--color-border, #e2e8f0)',
            paddingBottom: '12px'
          }}
        >
          <h2
            style={{
              margin: 0,
              fontSize: '16px',
              fontWeight: 600,
              color: 'var(--color-text-main, #0f172a)'
            }}
          >
            {title}
          </h2>
        </div>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: '16px'
        }}
      >
        {/* Widget 1: Daily Credit Usage */}
        <CreditProgressWidget
          title="Daily Credit Usage"
          ariaLabel="Daily credit usage"
          used={resolvedDailyUsed}
          budget={resolvedDailyBudget}
        />

        {/* Widget 2: Monthly Credit Usage */}
        <CreditProgressWidget
          title="Monthly Credit Usage"
          ariaLabel="Monthly credit usage"
          used={resolvedMonthlyUsed}
          budget={resolvedMonthlyBudget}
        />
      </div>
    </section>
  )
}

export default CreditMeter
