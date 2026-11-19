import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

/** "11–20 of 47" with Previous / Next under a paged list; nothing when it all fits on one page. */
export default function Pager({ paged, label = 'items' }) {
  if (!paged || paged.pageCount <= 1) return null;
  const { page, pageCount, from, to, total, setPage } = paged;
  return (
    <nav className="pager" aria-label={`Pages of ${label}`}>
      <span className="muted small" aria-live="polite">{from}–{to} of {total} {label}</span>
      <span className="row">
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setPage(page - 1)} disabled={page <= 1}
          aria-label={`Previous page of ${label}`}>
          <ChevronLeft size={14} /> Previous
        </button>
        <span className="small" aria-current="page">Page {page} of {pageCount}</span>
        <button type="button" className="btn btn-sm btn-ghost" onClick={() => setPage(page + 1)} disabled={page >= pageCount}
          aria-label={`Next page of ${label}`}>
          Next <ChevronRight size={14} />
        </button>
      </span>
    </nav>
  );
}
