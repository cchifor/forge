import { describe, expect, it } from 'vitest';
import { appPath } from './paths';

describe('app-relative navigation paths', () => {
  it('keeps internal paths, query parameters and hashes', () => {
    expect(appPath('/items/42?tab=details#history')).toBe('items/42?tab=details#history');
    expect(appPath('/')).toBe('');
  });
  it('strips the deployment base once', () => {
    expect(appPath('/console/items/42', '/console/')).toBe('items/42');
    expect(appPath('/console', '/console/')).toBe('');
    expect(appPath('/console-other/items', '/console/')).toBe('');
  });
  it('rejects external and script redirects', () => {
    expect(appPath('https://outside.example/items')).toBe('');
    expect(appPath('//outside.example/items')).toBe('');
    expect(appPath('javascript:alert(1)')).toBe('');
    expect(appPath('http://[')).toBe('');
  });
});
