<script lang="ts">
	import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge';

	import type { WorkspaceAction, WorkspaceActivity } from '../../chat.types';

	// MCP-extension iframe sandbox.
	//
	// Phase 4 of Pillar B in the architectural improvement plan: Svelte's
	// McpExtEngine now mounts the iframe + wires the AppBridge, matching
	// the Vue reference at `forge/templates/apps/vue-frontend-template/.../McpExtEngine.vue`.
	// Before this change, the Svelte engine only resolved the workspace
	// component registry — the iframe never appeared, so MCP-ext activities
	// silently rendered as empty boxes.
	//
	// The protocol surface (typed handlers, `MCP_BRIDGE_AVAILABLE` flag) is
	// re-exported by `@forge/canvas-svelte` from `@forge/canvas-core` for
	// downstream code that wants to drive a bridge from outside an iframe
	// component, but inside the template we use the upstream package
	// directly to keep the build dep graph honest: the template's
	// `package.json.jinja` already pulls `@modelcontextprotocol/ext-apps`
	// for both stacks.

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	let iframeEl: HTMLIFrameElement | undefined = $state();
	let bridge: AppBridge | null = null;

	function emitAction(action: WorkspaceAction) {
		// MCP tool callouts mirror AG-UI submit semantics — the agent reducer
		// turns the answer back into an HTTP response.
		onAction?.(action);
	}

	$effect(() => {
		const iframe = iframeEl;
		if (!iframe?.contentWindow) return;

		const localBridge = new AppBridge(
			null,
			{ name: activity.activityType || 'mcp-app', version: '1.0.0' },
			{ openLinks: {}, logging: {} },
			{
				hostContext: {
					theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
					displayMode: 'inline'
				}
			}
		);

		localBridge.oninitialized = () => {
			const initial = (activity.content as Record<string, unknown>).initialContext ?? activity.content;
			localBridge.sendToolInput({ arguments: initial as Record<string, unknown> });
		};

		localBridge.onmessage = async ({ content }: { content: Array<{ type?: string; text?: string }> }) => {
			const text = content?.find((c) => c.type === 'text')?.text;
			if (text) emitAction({ type: 'mcp_message', data: { text } });
			return {};
		};

		localBridge.onopenlink = async ({ url }: { url: string }) => {
			window.open(url, '_blank', 'noopener,noreferrer');
			return {};
		};

		localBridge.onsizechange = ({ height }: { height: number }) => {
			if (height && iframe) iframe.style.height = `${height}px`;
		};

		// Bidirectional tool calls — the MCP app inside the iframe asks the
		// host to run a tool; we route through `onAction` so the chat layer
		// can decide whether to invoke locally or escalate.
		if ('ontoolcall' in localBridge) {
			(localBridge as unknown as { ontoolcall: (req: { name: string; arguments: Record<string, unknown> }) => Promise<Record<string, unknown>> }).ontoolcall = async ({
				name,
				arguments: args
			}) => {
				emitAction({ type: 'mcp_tool_call', data: { toolName: name, args: args ?? {} } });
				return {};
			};
		}

		bridge = localBridge;

		const transport = new PostMessageTransport(iframe.contentWindow, iframe.contentWindow);
		void localBridge.connect(transport).then(() => {
			// Guard: if the cleanup already torn this bridge down (component
			// unmounted between connect() call and resolve), don't push the
			// sandbox resource into a dead bridge.
			if (bridge !== localBridge) return;
			const html = (activity.content as Record<string, unknown>).html;
			if (typeof html === 'string') {
				localBridge.sendSandboxResourceReady({
					html,
					csp: (activity.content as Record<string, unknown>).csp as string | undefined,
					permissions: (activity.content as Record<string, unknown>).permissions as
						| string[]
						| undefined
				});
			}
		});

		return () => {
			void localBridge.teardownResource({}).catch(() => {});
			if (bridge === localBridge) bridge = null;
		};
	});

	// Push fresh tool input when the activity content changes — mirrors
	// the Vue `watch(deep: true)` shape so MCP apps see the updated
	// arguments without a full remount.
	$effect(() => {
		const newContent = activity.content as Record<string, unknown>;
		if (!bridge) return;
		try {
			bridge.sendToolInput({
				arguments: ((newContent.initialContext as Record<string, unknown>) ??
					newContent) as Record<string, unknown>
			});
		} catch {
			// Bridge may not be connected yet — the first $effect handles
			// the initial send.
		}
	});

	export function sendToolResult(result: unknown): void {
		if (bridge && 'sendToolResult' in bridge) {
			(bridge as unknown as { sendToolResult: (r: unknown) => void }).sendToolResult(result);
		}
	}
</script>

<iframe
	bind:this={iframeEl}
	src={(activity.content as Record<string, unknown>).entryUrl as string | undefined}
	sandbox="allow-scripts allow-same-origin allow-forms"
	class="w-full h-full border-0"
	title="MCP Extension"
></iframe>
