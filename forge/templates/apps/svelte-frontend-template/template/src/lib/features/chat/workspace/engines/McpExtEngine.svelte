<script lang="ts">
	import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge';
	import type { UpstreamAppBridge } from '@forge/canvas-core';

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
	// Typed as canvas-core's UpstreamAppBridge — the permissive host-facing
	// surface (onsizechange/teardownResource/sendSandboxResourceReady) that
	// matches the `new AppBridge(null, …)` construction below. The upstream
	// package's own exported type is stricter (expects a Client first arg and
	// a domains-object `permissions`), so we adapt at the construction seam.
	let bridge: UpstreamAppBridge | null = null;

	function emitAction(action: WorkspaceAction) {
		// MCP tool callouts mirror AG-UI submit semantics — the agent reducer
		// turns the answer back into an HTTP response.
		onAction?.(action);
	}

	$effect(() => {
		const iframe = iframeEl;
		if (!iframe?.contentWindow) return;

		const localBridge = new AppBridge(
			// host has no MCP Client in this iframe-sandbox flow; the upstream
			// ctor accepts null at runtime — adapt to the permissive host surface.
			null as never,
			{ name: activity.activityType || 'mcp-app', version: '1.0.0' },
			{ openLinks: {}, logging: {} },
			{
				hostContext: {
					theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
					displayMode: 'inline'
				}
			}
		) as unknown as UpstreamAppBridge;

		localBridge.oninitialized = () => {
			const initial = (activity.content as Record<string, unknown>).initialContext ?? activity.content;
			localBridge.sendToolInput({ arguments: initial as Record<string, unknown> });
		};

		localBridge.onmessage = async (msg) => {
			// The upstream MCP message carries an array of content blocks; the
			// canvas-core BridgeMessage type models `content` as a string, so go
			// through `unknown` to read the richer runtime shape.
			const content = (msg as unknown as { content?: Array<{ type?: string; text?: string }> })
				.content;
			const text = content?.find((c) => c.type === 'text')?.text;
			if (text) emitAction({ type: 'mcp_message', data: { text } });
		};

		localBridge.onopenlink = async (req) => {
			const url = (req as { url?: string }).url;
			if (url) window.open(url, '_blank', 'noopener,noreferrer');
		};

		localBridge.onsizechange = ({ height }) => {
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
			// sendSandboxResourceReady is optional on the bridge surface — only
			// the iframe sandbox-resource flow implements it. Guard the call.
			if (typeof html === 'string' && typeof localBridge.sendSandboxResourceReady === 'function') {
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

	// Push fresh tool input when the activity content changes.
	//
	// **Vue↔Svelte divergence — intentional.** Vue's `watch(prop,
	// { deep: true })` re-runs on nested property mutations of
	// `activity.content`. Svelte 5's `$effect` only re-runs when the
	// *reference* to `activity.content` changes. We rely on the latter
	// because the AG-UI protocol contract is "every activity update is
	// a fresh immutable snapshot": canvas-core's reducer (see
	// `packages/canvas-core/src/reducer.ts` — `ACTIVITY_SNAPSHOT` case)
	// always constructs a new `WorkspaceActivity` object with a new
	// `content` reference per inbound event. No producer mutates
	// `activity.content` in place. If a future producer ever does, the
	// proper fix is to update the producer to honor the immutable-
	// snapshot contract — not to add deep-watching here, which would
	// paper over the protocol violation.
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
