<script lang="ts">
	import { untrack } from 'svelte';
	import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge';
	import {
		mountMcpExtBridge,
		type MountMcpExtBridgeHandle,
		type AppBridgeConstructor,
		type PostMessageTransportConstructor
	} from '@forge/canvas-core';

	import type { WorkspaceAction, WorkspaceActivity } from '../../chat.types';

	// MCP-extension iframe sandbox. canvas-core's `mountMcpExtBridge` owns the
	// AppBridge construct/connect/teardown lifecycle and adapts the real
	// @modelcontextprotocol/ext-apps@0.4.2 handler signatures onto the simplified
	// callbacks below (constructor-injected so canvas-core stays dep-free). The
	// upstream class is cast to the adapter ctor type at the injection seam.

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	let iframeEl: HTMLIFrameElement | undefined = $state();
	let handle: MountMcpExtBridgeHandle | null = null;

	$effect(() => {
		const iframe = iframeEl;
		if (!iframe?.contentWindow) return;
		// Mount ONCE per iframe element: this effect tracks only `iframeEl`. The
		// activity reads below are untracked so a later content change doesn't
		// tear down + recreate the bridge — the content $effect handles updates.
		handle = untrack(() => {
			const content = activity.content as Record<string, unknown>;
			return mountMcpExtBridge({
				appBridgeCtor: AppBridge as unknown as AppBridgeConstructor,
				transportCtor: PostMessageTransport as unknown as PostMessageTransportConstructor,
				iframe,
				identity: { name: activity.activityType || 'mcp-app', version: '1.0.0' },
				capabilities: { openLinks: {}, logging: {} },
				context: {
					hostContext: {
						theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
						displayMode: 'inline'
					}
				},
				callbacks: {
					onInitialized: ({ sendToolInput }) => {
						sendToolInput((content.initialContext ?? content) as Record<string, unknown>);
					},
					onMessage: (msg) => {
						if (msg.content) onAction?.({ type: 'mcp_message', data: { text: msg.content } });
					},
					onOpenLink: ({ url }) => {
						window.open(url, '_blank', 'noopener,noreferrer');
					},
					onSizeChange: ({ height }) => {
						if (height && iframe) iframe.style.height = `${height}px`;
					},
					onToolCall: async ({ name, arguments: args }) => {
						// Forward to the chat layer; no synchronous result, so return a
						// valid empty CallToolResult.
						onAction?.({ type: 'mcp_tool_call', data: { toolName: name, args: args ?? {} } });
						return { content: [] };
					}
				},
				html: content.html as string | undefined,
				csp: content.csp as string | undefined,
				permissions: content.permissions
			});
		});

		return () => {
			handle?.cleanup();
			handle = null;
		};
	});

	// Push fresh tool input when the activity content changes.
	//
	// **Vue↔Svelte divergence — intentional.** Svelte 5's `$effect` re-runs only
	// when the `activity.content` *reference* changes; the AG-UI contract is that
	// every activity update is a fresh immutable snapshot (canvas-core's reducer
	// builds a new `content` reference per event), so a ref-change effect is
	// correct. If a producer ever mutates `content` in place, fix the producer —
	// don't add deep-watching here.
	$effect(() => {
		const newContent = activity.content as Record<string, unknown>;
		handle?.sendToolInput((newContent.initialContext ?? newContent) as Record<string, unknown>);
	});

	export function sendToolResult(result: unknown): void {
		handle?.sendToolResult(result);
	}
</script>

<iframe
	bind:this={iframeEl}
	src={(activity.content as Record<string, unknown>).entryUrl as string | undefined}
	sandbox="allow-scripts allow-same-origin allow-forms"
	class="w-full h-full border-0"
	title="MCP Extension"
></iframe>
