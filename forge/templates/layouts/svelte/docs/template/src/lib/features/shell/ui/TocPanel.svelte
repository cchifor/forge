<script lang="ts">
	// TocPanel — the right table-of-contents column for the `docs` layout.
	//
	// Derives an in-page outline from the rendered article's <h2>/<h3> headings
	// and offers scroll-spy navigation. It re-scans on every route change (the
	// page swaps the article) and watches the article subtree for async content
	// via a MutationObserver. Active-heading tracking uses an IntersectionObserver
	// so the highlighted entry follows the scroll position.
	//
	// Self-contained: no shared store. The host passes the scrollable content
	// selector so the panel knows where to look and which container to spy on.
	import { onMount } from 'svelte';
	import { page } from '$app/stores';

	let { contentSelector = '[data-docs-content]' }: { contentSelector?: string } = $props();

	type Heading = { id: string; text: string; level: 2 | 3 };

	let headings = $state<Heading[]>([]);
	let activeId = $state<string>('');

	let mutationObserver: MutationObserver | null = null;
	let intersectionObserver: IntersectionObserver | null = null;

	function slugify(text: string, index: number): string {
		const base = text
			.toLowerCase()
			.trim()
			.replace(/[^\w\s-]/g, '')
			.replace(/\s+/g, '-');
		return base ? `${base}-${index}` : `section-${index}`;
	}

	function container(): HTMLElement | null {
		return document.querySelector<HTMLElement>(contentSelector);
	}

	function scan() {
		const root = container();
		if (!root) {
			headings = [];
			return;
		}
		const found: Heading[] = [];
		const els = root.querySelectorAll<HTMLHeadingElement>('h2, h3');
		els.forEach((el, i) => {
			// Ensure every heading has a stable anchor id for deep-linking + spy.
			if (!el.id) el.id = slugify(el.textContent ?? '', i);
			found.push({
				id: el.id,
				text: el.textContent?.trim() ?? '',
				level: el.tagName === 'H3' ? 3 : 2
			});
		});
		headings = found;
		observeHeadings(els);
		if (found.length && !found.some((h) => h.id === activeId)) {
			activeId = found[0].id;
		}
	}

	function observeHeadings(els: NodeListOf<HTMLHeadingElement>) {
		intersectionObserver?.disconnect();
		intersectionObserver = null;
		if (!els.length) return;
		const observer = new IntersectionObserver(
			(entries) => {
				const visible = entries
					.filter((e) => e.isIntersecting)
					.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
				if (visible[0]?.target.id) activeId = visible[0].target.id;
			},
			{ rootMargin: '0px 0px -70% 0px', threshold: 0 }
		);
		els.forEach((el) => {
			if (el) observer.observe(el);
		});
		intersectionObserver = observer;
	}

	function scrollTo(id: string) {
		const el = document.getElementById(id);
		if (!el) return;
		el.scrollIntoView({ behavior: 'smooth', block: 'start' });
		activeId = id;
	}

	function rescanSoon() {
		// Give the new route's component a tick to render its article markup.
		requestAnimationFrame(() => requestAnimationFrame(scan));
	}

	onMount(() => {
		rescanSoon();
		const root = container();
		if (root) {
			mutationObserver = new MutationObserver(() => rescanSoon());
			mutationObserver.observe(root, { childList: true, subtree: true });
		}
		return () => {
			mutationObserver?.disconnect();
			intersectionObserver?.disconnect();
		};
	});

	// Re-scan whenever the route changes (the page swaps the article).
	$effect(() => {
		void $page.url.pathname;
		rescanSoon();
	});
</script>

<aside class="flex h-full w-[220px] shrink-0 flex-col overflow-hidden border-l bg-background">
	<div class="flex h-12 shrink-0 items-center px-4">
		<span class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
			On this page
		</span>
	</div>
	<nav class="flex-1 overflow-y-auto px-2 pb-4" aria-label="On this page">
		{#if !headings.length}
			<p class="px-2 text-sm text-muted-foreground">No sections on this page.</p>
		{:else}
			{#each headings as h (h.id)}
				<button
					type="button"
					class="block w-full truncate rounded-md py-1 text-left text-sm interactive-press
						{h.level === 3 ? 'pl-5 pr-2' : 'px-2'}
						{activeId === h.id
						? 'font-medium text-primary'
						: 'text-muted-foreground hover:text-foreground'}"
					title={h.text}
					onclick={() => scrollTo(h.id)}
				>
					{h.text}
				</button>
			{/each}
		{/if}
	</nav>
</aside>
