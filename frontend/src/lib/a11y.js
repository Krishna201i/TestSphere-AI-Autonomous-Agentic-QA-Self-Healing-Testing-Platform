/**
 * Props that make a clickable table row usable from the keyboard: it can be
 * focused (Tab), activated with Enter or Space, and announces its selection.
 */
export function selectableRow(onSelect, selected) {
  return {
    tabIndex: 0,
    'aria-selected': selected,
    onClick: onSelect,
    onKeyDown: (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelect();
      }
    },
  };
}
