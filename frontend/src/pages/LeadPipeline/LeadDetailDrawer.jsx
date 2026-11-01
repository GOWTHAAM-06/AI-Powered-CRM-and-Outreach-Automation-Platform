import { useEffect } from 'react'

const displayValue = (value) => {
  return value !== null && value !== undefined && value !== ''
    ? value
    : '—'
}

export default function LeadDetailDrawer({ lead, isOpen, onClose }) {
  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', handleEscape)

    return () => {
      window.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

  if (!isOpen || !lead) return null

  return (
    <>
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0,0,0,0.4)',
          zIndex: 999
        }}
      />

      <div
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          width: '500px',
          maxWidth: '100%',
          height: '100vh',
          overflowY: 'auto',
          backgroundColor: 'white',
          boxShadow: '-4px 0 20px rgba(0,0,0,0.15)',
          padding: '24px',
          zIndex: 1000
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '20px'
          }}
        >
          <h2>{displayValue(lead.title)}</h2>

          <button
            onClick={onClose}
            style={{
              border: 'none',
              background: 'none',
              cursor: 'pointer',
              fontSize: '22px'
            }}
          >
            ✕
          </button>
        </div>

        {/* Source Details */}
        <section style={{ marginBottom: '24px' }}>
          <h3>Source Information</h3>

          <p>
            <strong>Source Name:</strong>{' '}
            {displayValue(lead.source_name)}
          </p>

          <p>
  <strong>Publication Time:</strong>{' '}
  {lead?.published_at
    ? new Date(lead.published_at).toLocaleString()
    : '—'}
</p>

         <p>
  <strong>Discovery Time:</strong>{' '}
  {lead?.discovered_at
    ? new Date(lead.discovered_at).toLocaleString()
    : '—'}
</p>

          <p>
            <strong>Source URL:</strong>{' '}
            {lead.source_url ? (
              <a
                href={lead.source_url}
                target="_blank"
                rel="noreferrer"
              >
                Open Original Listing
              </a>
            ) : (
              '—'
            )}
          </p>
        </section>

        {/* Description */}
        <section style={{ marginBottom: '24px' }}>
          <h3>Opportunity Description</h3>

          <p>
            {displayValue(
              lead.description || lead.job_description
            )}
          </p>
        </section>

        {/* Contacts */}
        <section style={{ marginBottom: '24px' }}>
          <h3>Associated Contacts</h3>

          {lead.contacts?.length ? (
            lead.contacts.map((contact, index) => (
              <div
                key={index}
                style={{
                  border: '1px solid #e5e7eb',
                  padding: '12px',
                  borderRadius: '8px',
                  marginBottom: '10px'
                }}
              >
                <p>
                  <strong>Name:</strong>{' '}
                  {displayValue(contact.name)}
                </p>

                <p>
                  <strong>Role:</strong>{' '}
                  {displayValue(contact.role)}
                </p>

                <p>
                  <strong>Email:</strong>{' '}
                  {displayValue(contact.email)}
                </p>

                <p>
                  <strong>Phone:</strong>{' '}
                  {displayValue(contact.phone)}
                </p>

                <span
                  style={{
                    background: contact.verified
                      ? '#dcfce7'
                      : '#f3f4f6',
                    padding: '4px 8px',
                    borderRadius: '12px',
                    fontSize: '12px'
                  }}
                >
                  {contact.verified ? 'Verified' : 'Unverified'}
                </span>
              </div>
            ))
          ) : (
            <p>—</p>
          )}
        </section>

        {/* Score Breakdown */}
        <section style={{ marginBottom: '24px' }}>
          <h3>Score Breakdown</h3>

          {lead.score_breakdown?.length ? (
            lead.score_breakdown.map((item, index) => (
              <div
                key={index}
                style={{
                  borderBottom: '1px solid #eee',
                  padding: '8px 0'
                }}
              >
                <p>
                  <strong>Factor:</strong>{' '}
                  {displayValue(item.factor)}
                </p>

                <p>
                  <strong>Score:</strong>{' '}
                  {displayValue(item.score)}
                </p>

                <p>
                  <strong>Reason Code:</strong>{' '}
                  {displayValue(item.reason_code)}
                </p>

                <p>
                  <strong>Explanation:</strong>{' '}
                  {displayValue(item.explanation)}
                </p>
              </div>
            ))
          ) : (
            <p>—</p>
          )}
        </section>

        {/* Audit Log */}
        <section>
          <h3>Audit History</h3>

          <div
            style={{
              border: '1px dashed #cbd5e1',
              padding: '16px',
              borderRadius: '8px'
            }}
          >
            Immutable audit log history will appear here.
          </div>
        </section>
      </div>
    </>
  )
}