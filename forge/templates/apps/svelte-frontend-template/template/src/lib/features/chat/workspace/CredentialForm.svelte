<script lang="ts">
	import type { WorkspaceAction, WorkspaceActivity } from '../chat.types';

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	interface CredentialField {
		name: string;
		label?: string;
		type?: 'text' | 'password' | 'email';
		required?: boolean;
		placeholder?: string;
	}

	const fields = $derived.by<CredentialField[]>(() => {
		const raw = activity.content.fields;
		return Array.isArray(raw) ? (raw as CredentialField[]) : [];
	});

	const title = $derived(
		typeof activity.content.title === 'string' ? activity.content.title : 'Provide credentials'
	);
	const description = $derived(
		typeof activity.content.description === 'string' ? activity.content.description : ''
	);

	let values = $state<Record<string, string>>({});

	function submit(e: SubmitEvent) {
		e.preventDefault();
		onAction?.({ type: 'submit', data: { ...values } });
	}
</script>

<form
	class="flex flex-col gap-3 p-4"
	onsubmit={submit}
	data-testid="credential-form"
>
	<header class="space-y-1">
		<h4 class="text-sm font-semibold">{title}</h4>
		{#if description}
			<p class="text-xs text-muted-foreground">{description}</p>
		{/if}
	</header>
	{#each fields as field (field.name)}
		<label class="flex flex-col gap-1 text-xs font-medium">
			<span>{field.label ?? field.name}</span>
			<input
				class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
				type={field.type ?? 'text'}
				required={field.required}
				placeholder={field.placeholder ?? ''}
				bind:value={values[field.name]}
			/>
		</label>
	{/each}
	<button
		type="submit"
		class="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
	>
		Submit
	</button>
</form>
