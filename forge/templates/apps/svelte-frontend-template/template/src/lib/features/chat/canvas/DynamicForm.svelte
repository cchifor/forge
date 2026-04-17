<script lang="ts">
	import type { WorkspaceAction, WorkspaceActivity } from '../chat.types';

	let {
		activity,
		onAction
	}: { activity: WorkspaceActivity; onAction?: (a: WorkspaceAction) => void } = $props();

	interface FormField {
		name: string;
		label?: string;
		type?: 'text' | 'number' | 'boolean' | 'textarea' | 'select';
		options?: Array<{ value: string; label: string }>;
		required?: boolean;
		default?: unknown;
		placeholder?: string;
	}

	const fields = $derived.by<FormField[]>(() => {
		const raw = activity.content.fields;
		return Array.isArray(raw) ? (raw as FormField[]) : [];
	});

	const title = $derived(
		typeof activity.content.title === 'string' ? activity.content.title : 'Form'
	);

	let values = $state<Record<string, unknown>>({});

	$effect(() => {
		// Seed defaults once when the activity changes.
		const defaults: Record<string, unknown> = {};
		for (const f of fields) {
			if (f.default !== undefined) defaults[f.name] = f.default;
		}
		values = defaults;
	});

	function submit(e: SubmitEvent) {
		e.preventDefault();
		onAction?.({ type: 'submit', data: { ...values } });
	}
</script>

<form class="flex flex-col gap-3 p-4" onsubmit={submit} data-testid="dynamic-form">
	<h4 class="text-sm font-semibold">{title}</h4>
	{#each fields as field (field.name)}
		<label class="flex flex-col gap-1 text-xs font-medium">
			<span>{field.label ?? field.name}</span>
			{#if field.type === 'textarea'}
				<textarea
					class="min-h-20 rounded-md border border-input bg-background px-2 py-1.5 text-sm"
					required={field.required}
					placeholder={field.placeholder ?? ''}
					bind:value={values[field.name] as string}
				></textarea>
			{:else if field.type === 'boolean'}
				<input
					type="checkbox"
					class="h-4 w-4"
					bind:checked={values[field.name] as boolean}
				/>
			{:else if field.type === 'select' && field.options}
				<select
					class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
					required={field.required}
					bind:value={values[field.name] as string}
				>
					{#each field.options as opt (opt.value)}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
			{:else}
				<input
					class="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
					type={field.type ?? 'text'}
					required={field.required}
					placeholder={field.placeholder ?? ''}
					bind:value={values[field.name] as string}
				/>
			{/if}
		</label>
	{/each}
	<button
		type="submit"
		class="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
	>
		Submit
	</button>
</form>
