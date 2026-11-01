import React from 'react'
import { renderToString } from 'react-dom/server'
import { describe, it, expect, vi } from 'vitest'
import {
  DEFAULT_FILTERS,
  createDefaultFilters,
  readFiltersFromUrl,
  writeFiltersToUrl,
} from '../../store/filters'
import { LeadFilters } from './LeadFilters'

describe('FE-10 LeadFilters and Store', () => {
  describe('Store Filter Defaults & URL Synchronization', () => {
    it('creates default filters with expected baseline values', () => {
      const defaults = createDefaultFilters()
      expect(defaults.search).toBe('')
      expect(defaults.sources).toEqual([])
      expect(defaults.experienceMin).toBe(0)
      expect(defaults.experienceMax).toBe(2)
      expect(defaults.scoreBand).toBe('all')
      expect(defaults.status).toBe('all')
      expect(defaults.assignedTo).toBe('all')
    })

    it('creates a fresh sources array copy on each createDefaultFilters call', () => {
      const first = createDefaultFilters()
      const second = createDefaultFilters()
      expect(first.sources).not.toBe(second.sources)
      first.sources.push('Internshala')
      expect(second.sources).toEqual([])
    })

    it('parses filters from URL query parameters correctly', () => {
      const queryString =
        '?search=Python+Dev&source=Internshala&source=LinkedIn&experienceMin=1&experienceMax=3&scoreBand=high&status=verified&assignedTo=user-123'
      const parsed = readFiltersFromUrl(queryString)

      expect(parsed.search).toBe('Python Dev')
      expect(parsed.sources).toEqual(['Internshala', 'LinkedIn'])
      expect(parsed.experienceMin).toBe(1)
      expect(parsed.experienceMax).toBe(3)
      expect(parsed.scoreBand).toBe('high')
      expect(parsed.status).toBe('verified')
      expect(parsed.assignedTo).toBe('user-123')
    })

    it('falls back to defaults when URL parameters are missing', () => {
      const parsed = readFiltersFromUrl('')
      expect(parsed.search).toBe(DEFAULT_FILTERS.search)
      expect(parsed.sources).toEqual([])
      expect(parsed.experienceMin).toBe(DEFAULT_FILTERS.experienceMin)
      expect(parsed.experienceMax).toBe(DEFAULT_FILTERS.experienceMax)
      expect(parsed.scoreBand).toBe(DEFAULT_FILTERS.scoreBand)
      expect(parsed.status).toBe(DEFAULT_FILTERS.status)
      expect(parsed.assignedTo).toBe(DEFAULT_FILTERS.assignedTo)
    })

    it('writes non-default filters to the browser history state', () => {
      const replaceStateMock = vi.fn()
      const originalWindow = globalThis.window

      globalThis.window = {
        location: {
          pathname: '/pipeline',
          hash: '',
        },
        history: {
          replaceState: replaceStateMock,
        },
      }

      writeFiltersToUrl({
        search: 'FastAPI',
        sources: ['Internshala'],
        experienceMin: 1,
        experienceMax: 4,
        scoreBand: 'high',
        status: 'new',
        assignedTo: 'user-7',
      })

      expect(replaceStateMock).toHaveBeenCalledTimes(1)
      const nextUrl = replaceStateMock.mock.calls[0][2]
      expect(nextUrl).toContain('search=FastAPI')
      expect(nextUrl).toContain('source=Internshala')
      expect(nextUrl).toContain('experienceMin=1')
      expect(nextUrl).toContain('experienceMax=4')
      expect(nextUrl).toContain('scoreBand=high')
      expect(nextUrl).toContain('status=new')
      expect(nextUrl).toContain('assignedTo=user-7')

      globalThis.window = originalWindow
    })
  })

  describe('Component Rendering', () => {
    const mockLeads = [
      {
        id: 'lead-1',
        title: 'Frontend Engineer',
        source_name: 'Internshala',
        assigned_to: 'Alice',
      },
      {
        id: 'lead-2',
        title: 'Backend Developer',
        source_name: 'Naukri Freshers',
        assigned_to: 'Bob',
      },
    ]

    it('renders search input, selectors, sliders, and clear button', () => {
      const filters = createDefaultFilters()
      const html = renderToString(
        <LeadFilters
          leads={mockLeads}
          filters={filters}
          onFiltersChange={() => {}}
          onSearchChange={() => {}}
          onClear={() => {}}
        />
      )

      expect(html).toContain('aria-label="Lead filters"')
      expect(html).toContain('Search company or job title...')
      expect(html).toContain('Score band')
      expect(html).toContain('Contact status')
      expect(html).toContain('Assigned user')
      expect(html).toContain('Internshala')
      expect(html).toContain('Naukri Freshers')
      expect(html).toContain('Experience range (years)')
      expect(html).toContain('Clear All Filters')
    })
  })
})
