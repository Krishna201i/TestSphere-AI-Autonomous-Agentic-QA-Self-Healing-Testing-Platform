import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { selectableRow } from '../lib/a11y';

describe('selectableRow', () => {
  it('makes a clickable row focusable and selectable from the keyboard', () => {
    const onSelect = vi.fn();
    render(<table><tbody><tr {...selectableRow(onSelect, false)}><td>finding</td></tr></tbody></table>);
    const row = screen.getByRole('row');
    expect(row.getAttribute('tabindex')).toBe('0');
    expect(row.getAttribute('aria-selected')).toBe('false');
    fireEvent.keyDown(row, { key: 'Enter' });
    fireEvent.keyDown(row, { key: ' ' });
    fireEvent.keyDown(row, { key: 'a' });
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledTimes(3);
  });
});
