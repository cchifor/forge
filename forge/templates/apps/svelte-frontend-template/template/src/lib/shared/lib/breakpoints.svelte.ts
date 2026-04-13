export type LayoutBreakpoint = 'compact' | 'medium' | 'expanded';

const MEDIUM_QUERY = '(min-width: 640px)';
const EXPANDED_QUERY = '(min-width: 1024px)';

let breakpoint = $state<LayoutBreakpoint>('expanded');
let screenWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 1200);

function computeBreakpoint(): LayoutBreakpoint {
	if (typeof window === 'undefined') return 'expanded';
	if (window.matchMedia(EXPANDED_QUERY).matches) return 'expanded';
	if (window.matchMedia(MEDIUM_QUERY).matches) return 'medium';
	return 'compact';
}

let initialized = false;

function initBreakpoints() {
	if (initialized) return;
	initialized = true;

	breakpoint = computeBreakpoint();
	screenWidth = window.innerWidth;

	const mediumMql = window.matchMedia(MEDIUM_QUERY);
	const expandedMql = window.matchMedia(EXPANDED_QUERY);

	function update() {
		breakpoint = computeBreakpoint();
		screenWidth = window.innerWidth;
	}

	mediumMql.addEventListener('change', update);
	expandedMql.addEventListener('change', update);
}

export function getBreakpointStore() {
	initBreakpoints();

	return {
		get breakpoint() {
			return breakpoint;
		},
		get screenWidth() {
			return screenWidth;
		},
		get isMobile() {
			return breakpoint === 'compact';
		},
		get isMedium() {
			return breakpoint === 'medium';
		},
		get isDesktop() {
			return breakpoint === 'expanded';
		}
	};
}
