import { cleanup, render } from '@testing-library/svelte';
import { afterEach, expect, it } from 'vitest';
import Report from '../canvas/Report.svelte';
import AiChatMessage from './AiChatMessage.svelte';

const markdown = '# Safe heading\n\n<img src="x" onerror="alert(1)"><script>alert(2)</script><a href="javascript:alert(3)">Link</a>';
afterEach(cleanup);

function expectSanitized(container: HTMLElement) {
  expect(container.querySelector('h1')?.textContent).toBe('Safe heading');
  expect(container.querySelector('script')).toBeNull();
  expect(container.querySelector('[onerror]')).toBeNull();
  expect(container.querySelector('a')?.getAttribute('href')).toBeNull();
}

it('sanitizes report Markdown before inserting HTML', () => {
  const { container } = render(Report, { activity: {
    engine: 'ag-ui', activityType: 'report', messageId: 'report-1', content: { markdown }
  } });
  expectSanitized(container);
});

it('sanitizes assistant Markdown before inserting HTML', () => {
  const { container } = render(AiChatMessage, { message: {
    id: 'message-1', role: 'assistant', content: markdown, isStreaming: false
  } });
  expectSanitized(container);
});
