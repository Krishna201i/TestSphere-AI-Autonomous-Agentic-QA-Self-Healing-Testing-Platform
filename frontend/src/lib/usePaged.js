import { useEffect, useMemo, useState } from 'react';

/**
 * Show a long list a page at a time.
 *
 * Returns the current page's items plus what the Pager needs.  When the list
 * shrinks (a filter, a deleted item) the page moves back to the last one that
 * still exists, so a card never shows an empty page.
 */
export function usePaged(items, pageSize = 10) {
  const list = items || [];
  const pageCount = Math.max(1, Math.ceil(list.length / pageSize));
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);

  const current = Math.min(page, pageCount);
  const start = (current - 1) * pageSize;
  const pageItems = useMemo(() => list.slice(start, start + pageSize), [list, start, pageSize]);

  return {
    items: pageItems,
    page: current,
    pageCount,
    total: list.length,
    from: list.length ? start + 1 : 0,
    to: Math.min(start + pageSize, list.length),
    // For lists that must print whole (Reports): render every item, and give
    // the ones off this page the "print-only-row" class
    isShown: (index) => index >= start && index < start + pageSize,
    setPage: (n) => setPage(Math.max(1, Math.min(n, pageCount))),
  };
}
