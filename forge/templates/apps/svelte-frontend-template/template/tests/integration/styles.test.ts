import { expect, it } from 'vitest';
import { cn } from '../../src/lib/shared/lib/utils';
it('resolves conditional class names and conflicting Tailwind styles together', () => {
  const button = document.createElement('button');
  button.className = cn('p-2', { 'opacity-50': true }, ['p-4', 'text-sm']);
  document.body.append(button);
  expect(button.classList.contains('p-2')).toBe(false);
  expect(button.classList.contains('p-4')).toBe(true);
  expect(button.classList.contains('opacity-50')).toBe(true);
  button.remove();
});
