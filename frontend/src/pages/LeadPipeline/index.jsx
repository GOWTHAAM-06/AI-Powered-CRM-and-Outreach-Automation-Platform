import React, { useState, useMemo } from 'react'
import { LeadTable } from './LeadTable'
import { LeadFilters } from './LeadFilters'
import {
  createDefaultFilters,
  readFiltersFromUrl,
} from '../../store/filters'
import { Button } from '../../components/ui/Button'
import LeadDetailDrawer from './LeadDetailDrawer'

export default function LeadPipelinePage({ currentUser }) {
  const [filters, setFilters] = useState(() => readFiltersFromUrl())
  const [selectedLead, setSelectedLead] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const tableFilters = useMemo(() => {
    return {
      search: filters.search || '',
      score_band: filters.scoreBand === 'all' ? '' : filters.scoreBand,
      status: filters.status === 'all' ? '' : filters.status,
      assigned_to: filters.assignedTo === 'all' ? '' : filters.assignedTo,
      source: filters.sources?.length === 1 ? filters.sources[0] : (filters.sources?.length > 1 ? filters.sources.join(',') : ''),
      experience_min: filters.experienceMin,
      experience_max: filters.experienceMax,
      ...filters,
    }
  }, [filters])

  return (
    <div
      style={{
        padding: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
        minWidth: 0,
        maxWidth: '100%',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div>
          <h1 style={{ fontSize: '22px', fontWeight: 700 }}>Lead Pipeline & Discovery</h1>
          <p style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
            Daily scraped 0-2 yr fresher opportunities across verified platforms.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setRefreshKey((k) => k + 1)}>
          ↻ Refresh
        </Button>
      </div>

      {/* Filter Bar (FE-10) */}
      <LeadFilters
        leads={[]}
        filters={filters}
        onFiltersChange={setFilters}
        onClear={() => {
          const defaults = createDefaultFilters()
          setFilters(defaults)
        }}
      />

      <LeadTable
        filters={tableFilters}
        currentUserId={currentUser?.id}
        selectedId={selectedLead?.id}
        refreshKey={refreshKey}
        onSelect={(lead) => setSelectedLead(lead)}
      />

      <LeadDetailDrawer
        lead={selectedLead}
        isOpen={!!selectedLead}
        onClose={() => setSelectedLead(null)}
      />
    </div>
  )
}