
export const DEFAULT_FILTERS = {
  search: '',
  sources: [],
  experienceMin: 0,
  experienceMax: 2,
  scoreBand: 'all',
  status: 'all',
  assignedTo: 'all'
}

export function createDefaultFilters() {
  return {
    ...DEFAULT_FILTERS,
    sources: [...DEFAULT_FILTERS.sources]
  }
}

export function readFiltersFromUrl(
  search = typeof window !== 'undefined' ? window.location?.search : ''
) {
  const params = new URLSearchParams(search)
  const defaults = createDefaultFilters()

  return {
    ...defaults,
    search: params.get('search') ?? defaults.search,
    sources: params.getAll('source'),
    experienceMin: Math.max(
      0,
      Number(params.get('experienceMin') ?? defaults.experienceMin)
    ),
    experienceMax: Math.max(
      0,
      Number(params.get('experienceMax') ?? defaults.experienceMax)
    ),
    scoreBand: params.get('scoreBand') ?? defaults.scoreBand,
    status: params.get('status') ?? defaults.status,
    assignedTo: params.get('assignedTo') ?? defaults.assignedTo
  }
}

export function writeFiltersToUrl(filters) {
  if (typeof window === 'undefined') return
  const params = new URLSearchParams()

  if (filters.search.trim()) params.set('search', filters.search.trim())
  filters.sources.forEach((source) => params.append('source', source))

  if (filters.experienceMin !== DEFAULT_FILTERS.experienceMin) {
    params.set('experienceMin', String(filters.experienceMin))
  }

  if (filters.experienceMax !== DEFAULT_FILTERS.experienceMax) {
    params.set('experienceMax', String(filters.experienceMax))
  }

  if (filters.scoreBand !== DEFAULT_FILTERS.scoreBand) {
    params.set('scoreBand', filters.scoreBand)
  }

  if (filters.status !== DEFAULT_FILTERS.status) {
    params.set('status', filters.status)
  }

  if (filters.assignedTo !== DEFAULT_FILTERS.assignedTo) {
    params.set('assignedTo', filters.assignedTo)
  }

  const query = params.toString()
  const nextUrl = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`

  window.history.replaceState(null, '', nextUrl)
}
