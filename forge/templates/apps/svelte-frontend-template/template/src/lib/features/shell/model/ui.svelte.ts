import { getBreakpointStore, type LayoutBreakpoint } from '$lib/shared/lib/breakpoints.svelte';
import { DesignTokens } from '$lib/shared/lib/design-tokens';

let sidebarCollapsed = $state(localStorage.getItem('sidebar-collapsed') === 'true');
let mobileMenuOpen = $state(false);
let chatOpen = $state(false);
let chatWidth = $state(parseInt(localStorage.getItem('chat-width') ?? '480', 10));
let chatWidthRatio = $state(
	parseFloat(localStorage.getItem('chat-width-ratio') ?? '0.33')
);

export type ChatMode = 'inline' | 'drawer' | 'sheet';

export function getUiStore() {
	const bp = getBreakpointStore();

	const breakpoint: LayoutBreakpoint = $derived(bp.breakpoint);
	const isMobile = $derived(bp.isMobile);
	const isMedium = $derived(bp.isMedium);
	const isDesktop = $derived(bp.isDesktop);

	const chatMode: ChatMode = $derived(
		isDesktop ? 'inline' : isMedium ? 'drawer' : 'sheet'
	);

	const effectiveSidebarWidth = $derived(
		isMobile
			? 0
			: isMedium
				? DesignTokens.sidebarCollapsedWidth
				: sidebarCollapsed
					? DesignTokens.sidebarCollapsedWidth
					: DesignTokens.sidebarExpandedWidth
	);

	// Auto-close sidebar when dropping below expanded
	let prevBreakpoint: LayoutBreakpoint | null = null;
	$effect(() => {
		if (prevBreakpoint === 'expanded' && breakpoint !== 'expanded') {
			chatOpen = false;
		}
		prevBreakpoint = breakpoint;
	});

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		localStorage.setItem('sidebar-collapsed', String(sidebarCollapsed));
	}

	function setSidebarCollapsed(value: boolean) {
		sidebarCollapsed = value;
		localStorage.setItem('sidebar-collapsed', String(value));
	}

	function toggleMobileMenu() {
		mobileMenuOpen = !mobileMenuOpen;
	}

	function closeMobileMenu() {
		mobileMenuOpen = false;
	}

	function toggleChat() {
		chatOpen = !chatOpen;
	}

	function openChat() {
		chatOpen = true;
	}

	function closeChat() {
		chatOpen = false;
	}

	function setChatWidth(width: number) {
		chatWidth = Math.max(DesignTokens.minChatWidth, Math.min(DesignTokens.maxChatWidth, width));
		localStorage.setItem('chat-width', String(chatWidth));
	}

	function setChatWidthRatio(ratio: number) {
		chatWidthRatio = Math.max(0.2, Math.min(0.5, ratio));
		localStorage.setItem('chat-width-ratio', String(chatWidthRatio));
	}

	return {
		get sidebarCollapsed() {
			return sidebarCollapsed;
		},
		get mobileMenuOpen() {
			return mobileMenuOpen;
		},
		get chatOpen() {
			return chatOpen;
		},
		get chatWidth() {
			return chatWidth;
		},
		get chatWidthRatio() {
			return chatWidthRatio;
		},
		get breakpoint() {
			return breakpoint;
		},
		get isMobile() {
			return isMobile;
		},
		get isMedium() {
			return isMedium;
		},
		get isDesktop() {
			return isDesktop;
		},
		get chatMode() {
			return chatMode;
		},
		get effectiveSidebarWidth() {
			return effectiveSidebarWidth;
		},
		toggleSidebar,
		setSidebarCollapsed,
		toggleMobileMenu,
		closeMobileMenu,
		toggleChat,
		openChat,
		closeChat,
		setChatWidth,
		setChatWidthRatio
	};
}
