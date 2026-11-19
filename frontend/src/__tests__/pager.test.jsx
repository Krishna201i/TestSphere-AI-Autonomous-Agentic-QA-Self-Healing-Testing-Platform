import React, { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import Pager from '../components/Pager';
import { usePaged } from '../lib/usePaged';

function List({ initial, size = 10 }) {
  const [items, setItems] = useState(initial);
  const paged = usePaged(items, size);
  return (
    <div>
      <ul>{paged.items.map((n) => <li key={n}>{n}</li>)}</ul>
      <Pager paged={paged} label="tests" />
      <button type="button" onClick={() => setItems(items.slice(0, 3))}>shrink</button>
    </div>
  );
}

const range = (n) => Array.from({ length: n }, (_, i) => `item ${i + 1}`);

afterEach(cleanup);

describe('paged lists', () => {
  it('shows no pager when everything fits on one page', () => {
    render(<List initial={range(10)} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(10);
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('shows one page at a time and moves between pages', () => {
    render(<List initial={range(23)} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(10);
    expect(screen.getByText('1–10 of 23 tests')).toBeTruthy();
    const prev = screen.getByRole('button', { name: 'Previous page of tests' });
    const next = screen.getByRole('button', { name: 'Next page of tests' });
    expect(prev.disabled).toBe(true);
    fireEvent.click(next);
    fireEvent.click(next);
    expect(screen.getByText('21–23 of 23 tests')).toBeTruthy();
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['item 21', 'item 22', 'item 23']);
    expect(next.disabled).toBe(true);
    expect(screen.getByText('Page 3 of 3')).toBeTruthy();
  });

  it('never strands the reader on a page that no longer exists', () => {
    render(<List initial={range(30)} />);
    fireEvent.click(screen.getByRole('button', { name: 'Next page of tests' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next page of tests' }));
    fireEvent.click(screen.getByRole('button', { name: 'shrink' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.queryByRole('navigation')).toBeNull();
  });
});
