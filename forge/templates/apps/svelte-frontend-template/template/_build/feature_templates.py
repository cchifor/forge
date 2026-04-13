"""TypeScript/Svelte code templates for dynamic feature generation.

All templates use Python str.format() with named placeholders.
Literal TypeScript/Svelte curly braces are escaped as {{ and }}.
"""


def make_feature_context(feature_name: str) -> dict:
    """Derive all naming variants from the feature name (expected plural)."""
    plural = feature_name.strip().lower()
    singular = (
        plural.rstrip("s")
        if plural.endswith("s") and len(plural) > 1
        else plural
    )
    return {
        "plural": plural,
        "singular": singular,
        "Plural": plural[0].upper() + plural[1:],
        "Singular": singular[0].upper() + singular[1:],
        "PLURAL": plural.upper(),
        "SINGULAR": singular.upper(),
    }


# ═══════════════════════════════════════════════════════════════
# FEATURE FILE TEMPLATES
# ═══════════════════════════════════════════════════════════════

FEATURE_INDEX = """\
export {{
\tcreate{Plural}ListQuery,
\tcreate{Singular}DetailQuery,
\tcreateCreate{Singular}Mutation,
\tcreateUpdate{Singular}Mutation,
\tcreateDelete{Singular}Mutation,
\ttype {Plural}QueryParams
}} from './api/{plural}';
export {{ create{Singular}Filters }} from './model/{singular}-filters.svelte';
export {{ create{Singular}Form }} from './model/{singular}-form.svelte';
export {{ default as {Singular}Card }} from './ui/{Singular}Card.svelte';
"""

FEATURE_API = """\
import {{ createQuery, createMutation, useQueryClient }} from '@tanstack/svelte-query';
import {{ derived, writable, type Readable }} from 'svelte/store';
import {{ getApiClient }} from '$lib/core/api/client';
import {{ validateResponse }} from '$lib/core/api/validation';
import {{ paginated{Singular}ResponseSchema, {singular}Schema }} from '$lib/core/schemas';
import type {{ API }} from '$lib/core/api/namespace';

export interface {Plural}QueryParams {{
\tskip?: number;
\tlimit?: number;
\tstatus?: string | undefined;
\tsearch?: string | undefined;
}}

export function create{Plural}ListQuery(paramsStore: Readable<{Plural}QueryParams>) {{
\tconst client = getApiClient();

\tconst options = derived(paramsStore, ($params) => ({{
\t\tqueryKey: ['{plural}', $params] as const,
\t\tqueryFn: async () => {{
\t\t\tconst searchParams = new URLSearchParams();
\t\t\tif ($params.skip != null) searchParams.set('skip', String($params.skip));
\t\t\tif ($params.limit != null) searchParams.set('limit', String($params.limit));
\t\t\tif ($params.status) searchParams.set('status', $params.status);
\t\t\tif ($params.search) searchParams.set('search', $params.search);
\t\t\tconst raw = await client.get('api/v1/{plural}', {{ searchParams }}).json();
\t\t\treturn validateResponse(paginated{Singular}ResponseSchema, raw, 'Paginated{Singular}Response');
\t\t}}
\t}}));

\treturn createQuery(options);
}}

export function create{Singular}DetailQuery(idStore: Readable<string>) {{
\tconst client = getApiClient();

\tconst options = derived(idStore, ($id) => ({{
\t\tqueryKey: ['{plural}', $id] as const,
\t\tqueryFn: async () => {{
\t\t\tconst raw = await client.get(`api/v1/{plural}/${{$id}}`).json();
\t\t\treturn validateResponse({singular}Schema, raw, '{Singular}');
\t\t}},
\t\tenabled: !!$id
\t}}));

\treturn createQuery(options);
}}

export function createCreate{Singular}Mutation() {{
\tconst client = getApiClient();
\tconst queryClient = useQueryClient();

\treturn createMutation({{
\t\tmutationFn: async (data: API.{Singular}Create) => {{
\t\t\tconst raw = await client.post('api/v1/{plural}', {{ json: data }}).json();
\t\t\treturn validateResponse({singular}Schema, raw, '{Singular}');
\t\t}},
\t\tonSuccess: () => {{
\t\t\tqueryClient.invalidateQueries({{ queryKey: ['{plural}'] }});
\t\t}}
\t}});
}}

export function createUpdate{Singular}Mutation() {{
\tconst client = getApiClient();
\tconst queryClient = useQueryClient();

\treturn createMutation({{
\t\tmutationFn: async ({{ id, data }}: {{ id: string; data: API.{Singular}Update }}) => {{
\t\t\tconst raw = await client.patch(`api/v1/{plural}/${{id}}`, {{ json: data }}).json();
\t\t\treturn validateResponse({singular}Schema, raw, '{Singular}');
\t\t}},
\t\tonSuccess: (_data, variables) => {{
\t\t\tqueryClient.invalidateQueries({{ queryKey: ['{plural}'] }});
\t\t\tqueryClient.invalidateQueries({{ queryKey: ['{plural}', variables.id] }});
\t\t}}
\t}});
}}

export function createDelete{Singular}Mutation() {{
\tconst client = getApiClient();
\tconst queryClient = useQueryClient();

\treturn createMutation({{
\t\tmutationFn: async (id: string) => {{
\t\t\tawait client.delete(`api/v1/{plural}/${{id}}`);
\t\t}},
\t\tonSuccess: () => {{
\t\t\tqueryClient.invalidateQueries({{ queryKey: ['{plural}'] }});
\t\t}}
\t}});
}}
"""

FEATURE_FILTERS = """\
import {{ writable, type Readable }} from 'svelte/store';
import type {{ {Plural}QueryParams }} from '../api/{plural}';

export function create{Singular}Filters(options?: {{ pageSize?: number }}) {{
\tconst pageSize = options?.pageSize ?? 20;

\tlet currentPage = $state(0);
\tlet statusFilter = $state<string | undefined>(undefined);
\tlet searchInput = $state('');
\tlet searchQuery = $state('');
\tconst skip = $derived(currentPage * pageSize);

\tlet searchTimeout: ReturnType<typeof setTimeout>;
\t$effect(() => {{
\t\tconst val = searchInput;
\t\tclearTimeout(searchTimeout);
\t\tsearchTimeout = setTimeout(() => {{
\t\t\tsearchQuery = val;
\t\t\tcurrentPage = 0;
\t\t}}, 300);
\t\treturn () => clearTimeout(searchTimeout);
\t}});

\tconst paramsStore = writable<{Plural}QueryParams>({{ skip: 0, limit: pageSize }});

\t$effect(() => {{
\t\tparamsStore.set({{
\t\t\tskip,
\t\t\tlimit: pageSize,
\t\t\tstatus: statusFilter,
\t\t\tsearch: searchQuery || undefined
\t\t}});
\t}});

\treturn {{
\t\tget currentPage() {{ return currentPage; }},
\t\tset currentPage(v: number) {{ currentPage = v; }},
\t\tget statusFilter() {{ return statusFilter; }},
\t\tset statusFilter(v: string | undefined) {{ statusFilter = v; currentPage = 0; }},
\t\tget searchInput() {{ return searchInput; }},
\t\tset searchInput(v: string) {{ searchInput = v; }},
\t\tget searchQuery() {{ return searchQuery; }},
\t\tget skip() {{ return skip; }},
\t\tget pageSize() {{ return pageSize; }},
\t\tget paramsStore(): Readable<{Plural}QueryParams> {{ return paramsStore; }},
\t\tnextPage() {{ currentPage++; }},
\t\tprevPage() {{ if (currentPage > 0) currentPage--; }},
\t\tresetPage() {{ currentPage = 0; }}
\t}};
}}
"""

FEATURE_FORM = """\
import type {{ API }} from '$lib/core/api/namespace';

export function create{Singular}Form(initial?: {{
\tname: string;
\tdescription: string | null;
\tstatus: string;
\ttags: string[];
}}) {{
\tlet name = $state(initial?.name ?? '');
\tlet description = $state(initial?.description ?? '');
\tlet status = $state(initial?.status ?? 'DRAFT');
\tlet tagsInput = $state(initial?.tags?.join(', ') ?? '');

\tconst parsedTags = $derived(
\t\ttagsInput.split(',').map((t) => t.trim()).filter(Boolean)
\t);
\tconst isValid = $derived(name.trim().length > 0);

\treturn {{
\t\tget name() {{ return name; }},
\t\tset name(v: string) {{ name = v; }},
\t\tget description() {{ return description; }},
\t\tset description(v: string) {{ description = v; }},
\t\tget status() {{ return status; }},
\t\tset status(v: string) {{ status = v; }},
\t\tget tagsInput() {{ return tagsInput; }},
\t\tset tagsInput(v: string) {{ tagsInput = v; }},
\t\tget parsedTags() {{ return parsedTags; }},
\t\tget isValid() {{ return isValid; }},
\t\treset(data: {{ name: string; description: string | null; status: string; tags: string[] }}) {{
\t\t\tname = data.name;
\t\t\tdescription = data.description ?? '';
\t\t\tstatus = data.status;
\t\t\ttagsInput = data.tags.join(', ');
\t\t}},
\t\ttoCreatePayload(): API.{Singular}Create {{
\t\t\treturn {{
\t\t\t\tname: name.trim(),
\t\t\t\tdescription: description.trim() || undefined,
\t\t\t\ttags: parsedTags,
\t\t\t\tstatus: status as API.{Singular}Status
\t\t\t}};
\t\t}},
\t\ttoUpdatePayload(): API.{Singular}Update {{
\t\t\treturn {{
\t\t\t\tname: name.trim(),
\t\t\t\tdescription: description.trim() || null,
\t\t\t\tstatus: status as API.{Singular}Status,
\t\t\t\ttags: parsedTags
\t\t\t}};
\t\t}}
\t}};
}}
"""

FEATURE_SCHEMA = """\
import {{ z }} from 'zod';
import {{ paginatedResponseSchema }} from './common.schema';

export const {singular}StatusSchema = z.enum(['DRAFT', 'ACTIVE', 'ARCHIVED']);

export const {singular}Schema = z.object({{
\tid: z.string().uuid(),
\tname: z.string(),
\tdescription: z.string().nullable(),
\ttags: z.array(z.string()),
\tstatus: {singular}StatusSchema,
\tcustomer_id: z.string().uuid(),
\tuser_id: z.string().uuid(),
\tcreated_at: z.string().nullable(),
\tupdated_at: z.string().nullable()
}});

export const paginated{Singular}ResponseSchema = paginatedResponseSchema({singular}Schema);

export type {Singular}Parsed = z.infer<typeof {singular}Schema>;
export type Paginated{Singular}ResponseParsed = z.infer<typeof paginated{Singular}ResponseSchema>;
"""

# Card component - this is a .svelte file so no Jinja2 issues
FEATURE_CARD = """\
<script lang="ts">
\timport {{ MoreHorizontal, Eye, Trash2 }} from 'lucide-svelte';
\timport {{ StatusBadge }} from '$lib/shared';

\tlet {{ item, onview, ondelete }}: {{
\t\titem: {{ id: string; name: string; description: string | null; tags: string[]; status: string; created_at: string | null }};
\t\tonview?: () => void;
\t\tondelete?: () => void;
\t}} = $props();

\tlet menuOpen = $state(false);

\tfunction formatDate(d: string | null) {{
\t\tif (!d) return '-';
\t\treturn new Date(d).toLocaleDateString(undefined, {{ year: 'numeric', month: 'short', day: 'numeric' }});
\t}}
</script>

<div
\tclass="rounded-lg border bg-card p-4 transition-colors hover:bg-accent/50 cursor-pointer"
\tdata-testid="{singular}-card"
\tonclick={{onview}}
\trole="button"
\ttabindex="0"
\tonkeydown={{(e) => e.key === 'Enter' && onview?.()}}
>
\t<div class="flex items-start justify-between gap-2">
\t\t<div class="min-w-0 flex-1">
\t\t\t<h3 class="font-medium truncate" data-testid="{singular}-name">{{item.name}}</h3>
\t\t\t{{#if item.description}}
\t\t\t\t<p class="text-sm text-muted-foreground line-clamp-2 mt-0.5">{{item.description}}</p>
\t\t\t{{/if}}
\t\t</div>
\t\t<div class="flex items-center gap-2 shrink-0">
\t\t\t<StatusBadge status={{item.status}} />
\t\t\t<!-- svelte-ignore a11y_no_static_element_interactions -->
\t\t\t<div class="relative" onclick={{(e) => e.stopPropagation()}} onkeydown={{(e) => e.stopPropagation()}}>
\t\t\t\t<button class="btn-press rounded-md p-1 transition-colors hover:bg-accent" onclick={{() => menuOpen = !menuOpen}}>
\t\t\t\t\t<MoreHorizontal class="h-4 w-4 text-muted-foreground" />
\t\t\t\t</button>
\t\t\t\t{{#if menuOpen}}
\t\t\t\t\t<!-- svelte-ignore a11y_no_static_element_interactions -->
\t\t\t\t\t<div class="fixed inset-0 z-40" onclick={{() => menuOpen = false}}></div>
\t\t\t\t\t<div class="absolute right-0 top-full mt-1 z-50 w-32 rounded-md border bg-popover p-1 shadow-md">
\t\t\t\t\t\t<button class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent" onclick={{() => {{ menuOpen = false; onview?.(); }}}}>
\t\t\t\t\t\t\t<Eye class="h-4 w-4" /> View
\t\t\t\t\t\t</button>
\t\t\t\t\t\t<button class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-destructive transition-colors hover:bg-accent" data-testid="{singular}-delete-btn" onclick={{() => {{ menuOpen = false; ondelete?.(); }}}}>
\t\t\t\t\t\t\t<Trash2 class="h-4 w-4" /> Delete
\t\t\t\t\t\t</button>
\t\t\t\t\t</div>
\t\t\t\t{{/if}}
\t\t\t</div>
\t\t</div>
\t</div>
\t{{#if item.tags.length > 0}}
\t\t<div class="flex flex-wrap gap-1 mt-2">
\t\t\t{{#each item.tags.slice(0, 4) as tag}}
\t\t\t\t<span class="rounded-full border px-2 py-0.5 text-xs">{{tag}}</span>
\t\t\t{{/each}}
\t\t\t{{#if item.tags.length > 4}}
\t\t\t\t<span class="rounded-full border px-2 py-0.5 text-xs">+{{item.tags.length - 4}}</span>
\t\t\t{{/if}}
\t\t</div>
\t{{/if}}
\t<p class="text-xs text-muted-foreground mt-2">{{formatDate(item.created_at)}}</p>
</div>
"""

# Route pages
ROUTE_LIST = """\
<script lang="ts">
\timport {{ goto }} from '$app/navigation';
\timport {{ Plus }} from 'lucide-svelte';
\timport {{ toast }} from 'svelte-sonner';
\timport {{ ConfirmDialog, EmptyState, SearchField, SegmentedButton }} from '$lib/shared';
\timport {{
\t\tcreate{Plural}ListQuery,
\t\tcreateDelete{Singular}Mutation,
\t\tcreate{Singular}Filters,
\t\t{Singular}Card
\t}} from '$lib/features/{plural}';

\tconst filters = create{Singular}Filters();
\tconst {plural}Query = create{Plural}ListQuery(filters.paramsStore);
\tconst deleteMutation = createDelete{Singular}Mutation();

\tlet deleteDialogOpen = $state(false);
\tlet {singular}ToDelete = $state<{{ id: string; name: string }} | null>(null);
\tlet statusFilterValue = $state('all');

\tfunction confirmDelete({singular}: {{ id: string; name: string }}) {{
\t\t{singular}ToDelete = {singular};
\t\tdeleteDialogOpen = true;
\t}}

\tasync function handleDelete() {{
\t\tif (!{singular}ToDelete) return;
\t\tconst name = {singular}ToDelete.name;
\t\ttry {{
\t\t\tawait $deleteMutation.mutateAsync({singular}ToDelete.id);
\t\t\ttoast.success(`{Singular} "${{name}}" deleted`);
\t\t}} catch {{
\t\t\t// handled by global mutation onError
\t\t}}
\t\t{singular}ToDelete = null;
\t}}
</script>

<div class="space-y-4" data-testid="{plural}-list">
\t<div class="flex items-center justify-between">
\t\t<div>
\t\t\t<h1 class="text-3xl font-bold tracking-tight">{Plural}</h1>
\t\t\t<p class="text-muted-foreground">Manage your {plural}</p>
\t\t</div>
\t\t<a href="/{plural}/new" data-testid="{plural}-create-btn" class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground ring-offset-background transition-colors hover:bg-primary/90">
\t\t\t<Plus class="h-4 w-4" /> New {Singular}
\t\t</a>
\t</div>

\t<div class="flex flex-col sm:flex-row gap-3">
\t\t<div class="flex-1 max-w-sm">
\t\t\t<SearchField bind:value={{filters.searchInput}} placeholder="Search {plural}..." data-testid="{plural}-search-input" />
\t\t</div>
\t\t<SegmentedButton
\t\t\toptions={{[
\t\t\t\t{{ value: 'all', label: 'All' }},
\t\t\t\t{{ value: 'DRAFT', label: 'Draft' }},
\t\t\t\t{{ value: 'ACTIVE', label: 'Active' }},
\t\t\t\t{{ value: 'ARCHIVED', label: 'Archived' }}
\t\t\t]}}
\t\t\tbind:value={{statusFilterValue}}
\t\t\tonchange={{(v) => {{ filters.statusFilter = v === 'all' ? undefined : v; }}}}
\t\t/>
\t</div>

\t{{#if ${plural}Query.isLoading}}
\t\t<div class="space-y-3">
\t\t\t{{#each Array(3) as _}}
\t\t\t\t<div class="h-24 rounded-lg border animate-pulse bg-muted"></div>
\t\t\t{{/each}}
\t\t</div>
\t{{:else if ${plural}Query.isError}}
\t\t<EmptyState message="Failed to load {plural}. Please try again." />
\t{{:else if ${plural}Query.data && ${plural}Query.data.items.length === 0}}
\t\t<EmptyState message="No {plural} found" />
\t{{:else if ${plural}Query.data}}
\t\t<div class="space-y-3">
\t\t\t{{#each ${plural}Query.data.items as {singular} ({singular}.id)}}
\t\t\t\t<{Singular}Card
\t\t\t\t\titem={{{singular}}}
\t\t\t\t\tonview={{() => goto(`/{plural}/${{{singular}.id}}`)}}
\t\t\t\t\tondelete={{() => confirmDelete({{ id: {singular}.id, name: {singular}.name }})}}
\t\t\t\t/>
\t\t\t{{/each}}
\t\t</div>
\t\t{{#if ${plural}Query.data.has_more}}
\t\t\t<div class="flex justify-center pt-4">
\t\t\t\t<button class="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-4 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground" onclick={{() => filters.nextPage()}}>
\t\t\t\t\tLoad More
\t\t\t\t</button>
\t\t\t</div>
\t\t{{/if}}
\t{{/if}}

\t<ConfirmDialog
\t\tbind:open={{deleteDialogOpen}}
\t\ttitle="Delete {Singular}"
\t\tdescription={{`Are you sure you want to delete '${{{singular}ToDelete?.name}}'? This cannot be undone.`}}
\t\tconfirmLabel="Delete"
\t\tonconfirm={{handleDelete}}
\t/>
</div>
"""

ROUTE_ERROR = """\
<script lang="ts">
\timport {{ page }} from '$app/stores';
\timport {{ invalidateAll }} from '$app/navigation';
\timport {{ Package }} from 'lucide-svelte';
\timport {{ userFacingMessage, categorizeError }} from '$lib/core/errors';

\tconst message = $derived(userFacingMessage($page.status, $page.error?.message));
\tconst category = $derived(categorizeError($page.status));
</script>

<div class="flex flex-col items-center justify-center gap-4 py-16 text-center px-4">
\t<Package class="h-12 w-12 text-muted-foreground" />
\t<h2 class="text-2xl font-bold">
\t\t{{category === 'not-found' ? '{Singular} Not Found' : `Error ${{$page.status}}`}}
\t</h2>
\t<p class="text-muted-foreground max-w-md">{{message}}</p>
\t<div class="flex gap-2">
\t\t{{#if category === 'server'}}
\t\t\t<button class="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90" onclick={{() => invalidateAll()}}>
\t\t\t\tTry Again
\t\t\t</button>
\t\t{{/if}}
\t\t<a href="/{plural}" class="inline-flex h-9 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground">
\t\t\tBack to {Plural}
\t\t</a>
\t</div>
</div>
"""

ROUTE_CREATE = """\
<script lang="ts">
\timport {{ goto }} from '$app/navigation';
\timport {{ ArrowLeft }} from 'lucide-svelte';
\timport {{ toast }} from 'svelte-sonner';
\timport {{ createCreate{Singular}Mutation, create{Singular}Form }} from '$lib/features/{plural}';

\tconst createMut = createCreate{Singular}Mutation();
\tconst form = create{Singular}Form();

\tfunction handleSubmit() {{
\t\tif (!form.isValid) {{
\t\t\ttoast.error('Name is required');
\t\t\treturn;
\t\t}}
\t\t$createMut.mutate(form.toCreatePayload(), {{
\t\t\tonSuccess: ({singular}) => {{
\t\t\t\ttoast.success(`{Singular} "${{{singular}.name}}" created`);
\t\t\t\tgoto(`/{plural}/${{{singular}.id}}`);
\t\t\t}}
\t\t}});
\t}}
</script>

<div class="space-y-4">
\t<div class="flex items-center gap-2">
\t\t<button class="btn-press inline-flex h-9 w-9 items-center justify-center rounded-md transition-colors hover:bg-accent hover:text-accent-foreground" onclick={{() => goto('/{plural}')}}>
\t\t\t<ArrowLeft class="h-4 w-4" />
\t\t</button>
\t\t<div>
\t\t\t<h1 class="text-3xl font-bold tracking-tight">New {Singular}</h1>
\t\t\t<p class="text-muted-foreground">Create a new {singular}</p>
\t\t</div>
\t</div>

\t<div class="max-w-2xl rounded-lg border bg-card text-card-foreground shadow-sm">
\t\t<div class="p-6">
\t\t\t<h3 class="text-lg font-semibold">{Singular} Details</h3>
\t\t\t<p class="mt-1.5 text-sm text-muted-foreground">Fill in the details</p>
\t\t</div>
\t\t<div class="p-6 pt-0">
\t\t\t<form class="space-y-4" onsubmit={{(e) => {{ e.preventDefault(); handleSubmit(); }}}}>
\t\t\t\t<div class="space-y-2">
\t\t\t\t\t<label for="name" class="text-sm font-medium">Name *</label>
\t\t\t\t\t<input id="name" type="text" placeholder="Enter name" required bind:value={{form.name}} data-testid="{singular}-name-input" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
\t\t\t\t</div>
\t\t\t\t<div class="space-y-2">
\t\t\t\t\t<label for="description" class="text-sm font-medium">Description</label>
\t\t\t\t\t<textarea id="description" rows="3" bind:value={{form.description}} data-testid="{singular}-description-input" class="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"></textarea>
\t\t\t\t</div>
\t\t\t\t<div class="space-y-2">
\t\t\t\t\t<label for="status" class="text-sm font-medium">Status</label>
\t\t\t\t\t<select id="status" bind:value={{form.status}} class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
\t\t\t\t\t\t<option value="DRAFT">Draft</option>
\t\t\t\t\t\t<option value="ACTIVE">Active</option>
\t\t\t\t\t\t<option value="ARCHIVED">Archived</option>
\t\t\t\t\t</select>
\t\t\t\t</div>
\t\t\t\t<div class="space-y-2">
\t\t\t\t\t<label for="tags" class="text-sm font-medium">Tags</label>
\t\t\t\t\t<input id="tags" type="text" placeholder="tag1, tag2 (comma-separated)" bind:value={{form.tagsInput}} class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
\t\t\t\t</div>
\t\t\t</form>
\t\t</div>
\t\t<div class="flex items-center gap-2 p-6 pt-0">
\t\t\t<button data-testid="{singular}-cancel-btn" class="inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground" onclick={{() => goto('/{plural}')}}>Cancel</button>
\t\t\t<button data-testid="{singular}-submit-btn" class="inline-flex h-10 items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50" disabled={{$createMut.isPending}} onclick={{handleSubmit}}>
\t\t\t\t{{$createMut.isPending ? 'Creating...' : 'Create {Singular}'}}
\t\t\t</button>
\t\t</div>
\t</div>
</div>
"""

ROUTE_DETAIL = """\
<script lang="ts">
\timport {{ goto }} from '$app/navigation';
\timport {{ page }} from '$app/stores';
\timport {{ derived }} from 'svelte/store';
\timport {{ ArrowLeft, Pencil, Trash2, Save, X }} from 'lucide-svelte';
\timport {{ toast }} from 'svelte-sonner';
\timport {{ ConfirmDialog }} from '$lib/shared';
\timport {{ create{Singular}DetailQuery, createUpdate{Singular}Mutation, createDelete{Singular}Mutation, create{Singular}Form }} from '$lib/features/{plural}';

\tconst idStore = derived(page, ($p) => $p.params.id ?? '');
\tconst {singular}Query = create{Singular}DetailQuery(idStore);
\tconst updateMut = createUpdate{Singular}Mutation();
\tconst deleteMut = createDelete{Singular}Mutation();
\tconst form = create{Singular}Form();

\tlet editing = $state(false);
\tlet deleteDialogOpen = $state(false);

\t$effect(() => {{
\t\tconst data = ${singular}Query.data;
\t\tif (data) form.reset(data);
\t}});

\tfunction saveEdit() {{
\t\tif (!form.isValid) {{ toast.error('Name is required'); return; }}
\t\t$updateMut.mutate(
\t\t\t{{ id: $page.params.id!, data: form.toUpdatePayload() }},
\t\t\t{{ onSuccess: () => {{ toast.success('{Singular} updated'); editing = false; }} }}
\t\t);
\t}}

\tasync function handleDelete() {{
\t\ttry {{
\t\t\tawait $deleteMut.mutateAsync($page.params.id!);
\t\t\ttoast.success('{Singular} deleted');
\t\t\tgoto('/{plural}');
\t\t}} catch {{}}
\t}}

\tfunction formatDate(d: string | null) {{ if (!d) return 'N/A'; return new Date(d).toLocaleString(); }}

\tfunction statusVariant(s: string) {{
\t\tswitch (s) {{
\t\t\tcase 'ACTIVE': return 'border-transparent bg-primary text-primary-foreground';
\t\t\tcase 'DRAFT': return 'border-transparent bg-secondary text-secondary-foreground';
\t\t\tdefault: return 'border bg-background text-foreground';
\t\t}}
\t}}
</script>

<div class="space-y-4" data-testid="{singular}-detail">
\t<div class="flex items-center gap-2">
\t\t<button class="btn-press inline-flex h-9 w-9 items-center justify-center rounded-md transition-colors hover:bg-accent hover:text-accent-foreground" onclick={{() => goto('/{plural}')}}>
\t\t\t<ArrowLeft class="h-4 w-4" />
\t\t</button>
\t\t<div class="flex-1">
\t\t\t<h1 class="text-3xl font-bold tracking-tight">{{${singular}Query.data?.name ?? '{Singular} Detail'}}</h1>
\t\t\t<p class="text-muted-foreground">View and manage details</p>
\t\t</div>
\t\t{{#if ${singular}Query.data && !editing}}
\t\t\t<button data-testid="{singular}-edit-btn" class="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground" onclick={{() => editing = true}}>
\t\t\t\t<Pencil class="h-4 w-4" /> Edit
\t\t\t</button>
\t\t\t<button data-testid="{singular}-delete-btn" class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground transition-colors hover:bg-destructive/90" onclick={{() => deleteDialogOpen = true}}>
\t\t\t\t<Trash2 class="h-4 w-4" /> Delete
\t\t\t</button>
\t\t{{/if}}
\t</div>

\t{{#if ${singular}Query.isLoading}}
\t\t<div class="rounded-lg border bg-card shadow-sm"><div class="space-y-4 p-6"><div class="h-8 w-48 animate-pulse rounded bg-muted"></div><div class="h-4 w-full animate-pulse rounded bg-muted"></div></div></div>
\t{{:else if ${singular}Query.isError}}
\t\t<div class="rounded-lg border bg-card shadow-sm"><div class="p-6 text-center text-muted-foreground">Failed to load. It may have been deleted.</div></div>
\t{{:else if ${singular}Query.data}}
\t\t<div class="max-w-2xl rounded-lg border bg-card shadow-sm">
\t\t\t<div class="p-6">
\t\t\t\t<h3 class="text-lg font-semibold">{{editing ? 'Edit {Singular}' : '{Singular} Details'}}</h3>
\t\t\t\t{{#if !editing}}<p class="mt-1.5 text-sm text-muted-foreground">ID: {{${singular}Query.data.id}}</p>{{/if}}
\t\t\t</div>
\t\t\t<div class="p-6 pt-0">
\t\t\t\t{{#if editing}}
\t\t\t\t\t<form class="space-y-4" onsubmit={{(e) => {{ e.preventDefault(); saveEdit(); }}}}>
\t\t\t\t\t\t<div class="space-y-2"><label for="edit-name" class="text-sm font-medium">Name *</label><input id="edit-name" required bind:value={{form.name}} class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>
\t\t\t\t\t\t<div class="space-y-2"><label for="edit-desc" class="text-sm font-medium">Description</label><textarea id="edit-desc" rows="3" bind:value={{form.description}} class="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"></textarea></div>
\t\t\t\t\t\t<div class="space-y-2"><label for="edit-status" class="text-sm font-medium">Status</label><select id="edit-status" bind:value={{form.status}} class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"><option value="DRAFT">Draft</option><option value="ACTIVE">Active</option><option value="ARCHIVED">Archived</option></select></div>
\t\t\t\t\t\t<div class="space-y-2"><label for="edit-tags" class="text-sm font-medium">Tags</label><input id="edit-tags" placeholder="tag1, tag2" bind:value={{form.tagsInput}} class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>
\t\t\t\t\t</form>
\t\t\t\t{{:else}}
\t\t\t\t\t<dl class="space-y-4">
\t\t\t\t\t\t<div><dt class="text-sm text-muted-foreground">Name</dt><dd class="text-sm font-medium">{{${singular}Query.data.name}}</dd></div>
\t\t\t\t\t\t<div><dt class="text-sm text-muted-foreground">Description</dt><dd class="text-sm">{{${singular}Query.data.description || 'No description'}}</dd></div>
\t\t\t\t\t\t<div><dt class="mb-1 text-sm text-muted-foreground">Status</dt><dd><span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold {{statusVariant(${singular}Query.data.status)}}">{{${singular}Query.data.status}}</span></dd></div>
\t\t\t\t\t\t<div><dt class="mb-1 text-sm text-muted-foreground">Tags</dt><dd class="flex flex-wrap gap-1">{{#each ${singular}Query.data.tags as tag}}<span class="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold">{{tag}}</span>{{/each}}{{#if ${singular}Query.data.tags.length === 0}}<span class="text-sm text-muted-foreground">No tags</span>{{/if}}</dd></div>
\t\t\t\t\t\t<div class="grid grid-cols-2 gap-4"><div><dt class="text-sm text-muted-foreground">Created</dt><dd class="text-sm">{{formatDate(${singular}Query.data.created_at)}}</dd></div><div><dt class="text-sm text-muted-foreground">Updated</dt><dd class="text-sm">{{formatDate(${singular}Query.data.updated_at)}}</dd></div></div>
\t\t\t\t\t</dl>
\t\t\t\t{{/if}}
\t\t\t</div>
\t\t\t{{#if editing}}
\t\t\t\t<div class="flex items-center gap-2 p-6 pt-0">
\t\t\t\t\t<button class="inline-flex h-10 items-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium transition-colors hover:bg-accent" onclick={{() => {{ if (${singular}Query.data) form.reset(${singular}Query.data); editing = false; }}}}><X class="h-4 w-4" /> Cancel</button>
\t\t\t\t\t<button data-testid="{singular}-save-btn" class="inline-flex h-10 items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50" disabled={{$updateMut.isPending}} onclick={{saveEdit}}><Save class="h-4 w-4" /> {{$updateMut.isPending ? 'Saving...' : 'Save'}}</button>
\t\t\t\t</div>
\t\t\t{{/if}}
\t\t</div>
\t{{/if}}

\t<ConfirmDialog bind:open={{deleteDialogOpen}} title="Delete {Singular}" description="Are you sure? This cannot be undone." confirmLabel="Delete" onconfirm={{handleDelete}} />
</div>
"""

# ═══════════════════════════════════════════════════════════════
# HUB INJECTION SNIPPETS
# ═══════════════════════════════════════════════════════════════

HUB_SIDEBAR_ITEM = """\t{{ title: '{Plural}', url: '/{plural}', icon: FolderOpen }},"""

HUB_BOTTOM_NAV_ITEM = """\t\t{{ title: '{Plural}', url: '/{plural}', icon: FolderOpen }},"""

HUB_BREADCRUMB = """\t\t'/{plural}': '{Plural}',\n\t\t'/{plural}/new': 'New {Singular}',"""

HUB_DASHBOARD_CHIP = """\t\t\t\t\t<a href="/{plural}" class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm hover:bg-accent transition-colors"><Package class="h-3.5 w-3.5" /> Browse {Plural}</a>\n\t\t\t\t\t<a href="/{plural}/new" class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm hover:bg-accent transition-colors"><Plus class="h-3.5 w-3.5" /> Create {Singular}</a>"""

HUB_SCHEMA_EXPORT = """export * from './{singular}.schema';"""

HUB_MSW_HANDLERS = """\
\thttp.get('*/api/v1/{plural}', () => {{
\t\treturn HttpResponse.json({{
\t\t\titems: [{{ id: '550e8400-e29b-41d4-a716-446655440001', name: 'Test {Singular}', description: 'A test {singular}', tags: ['test'], status: 'ACTIVE', customer_id: '550e8400-e29b-41d4-a716-446655440000', user_id: '550e8400-e29b-41d4-a716-446655440000', created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }}],
\t\t\ttotal: 1, skip: 0, limit: 50, has_more: false
\t\t}});
\t}}),

\thttp.post('*/api/v1/{plural}', async ({{ request }}) => {{
\t\tconst body = (await request.json()) as Record<string, unknown>;
\t\treturn HttpResponse.json({{ id: '550e8400-e29b-41d4-a716-446655440099', name: body.name, description: body.description ?? null, tags: body.tags ?? [], status: body.status ?? 'DRAFT', customer_id: '550e8400-e29b-41d4-a716-446655440000', user_id: '550e8400-e29b-41d4-a716-446655440000', created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }}, {{ status: 201 }});
\t}}),

\thttp.get('*/api/v1/{plural}/:id', ({{ params }}) => {{
\t\treturn HttpResponse.json({{ id: params.id, name: 'Test {Singular}', description: 'A test {singular}', tags: ['test'], status: 'ACTIVE', customer_id: '550e8400-e29b-41d4-a716-446655440000', user_id: '550e8400-e29b-41d4-a716-446655440000', created_at: '2025-01-01T00:00:00Z', updated_at: '2025-01-01T00:00:00Z' }});
\t}}),

\thttp.patch('*/api/v1/{plural}/:id', async ({{ params, request }}) => {{
\t\tconst body = (await request.json()) as Record<string, unknown>;
\t\treturn HttpResponse.json({{ id: params.id, name: body.name ?? 'Test {Singular}', description: body.description ?? null, tags: body.tags ?? ['test'], status: body.status ?? 'ACTIVE', customer_id: '550e8400-e29b-41d4-a716-446655440000', user_id: '550e8400-e29b-41d4-a716-446655440000', created_at: '2025-01-01T00:00:00Z', updated_at: new Date().toISOString() }});
\t}}),

\thttp.delete('*/api/v1/{plural}/:id', () => {{
\t\treturn new HttpResponse(null, {{ status: 204 }});
\t}}),"""

HUB_TYPES = """\
export type {Singular}Status = 'DRAFT' | 'ACTIVE' | 'ARCHIVED';

export interface {Singular}Create {{
\tname: string;
\tdescription?: string | null;
\ttags?: string[];
\tstatus?: {Singular}Status;
}}

export interface {Singular}Update {{
\tname?: string | null;
\tdescription?: string | null;
\ttags?: string[] | null;
\tstatus?: {Singular}Status | null;
}}

export interface {Singular} {{
\tid: string;
\tname: string;
\tdescription: string | null;
\ttags: string[];
\tstatus: {Singular}Status;
\tcustomer_id: string;
\tuser_id: string;
\tcreated_at: string | null;
\tupdated_at: string | null;
}}

export interface Paginated{Singular}Response {{
\titems: {Singular}[];
\ttotal: number;
\tskip: number;
\tlimit: number;
\thas_more: boolean;
}}
"""


# ═══════════════════════════════════════════════════════════════
# LAYOUT VARIANT (no chat)
# ═══════════════════════════════════════════════════════════════

NO_CHAT_LAYOUT = """\
<script lang="ts">
\timport { goto } from '$app/navigation';
\timport { getAuth } from '$lib/core';
\timport { getUiStore, AppSidebar, AppHeader } from '$lib/features/shell';
\timport BottomNav from '$lib/features/shell/ui/BottomNav.svelte';

\tlet { children } = $props();
\tconst auth = getAuth();
\tconst ui = getUiStore();

\t$effect(() => {
\t\tif (!auth.isLoading && !auth.isAuthenticated) {
\t\t\tgoto('/login');
\t\t}
\t});
</script>

{#if auth.isAuthenticated}
\t{#if ui.isMobile}
\t\t<div class="flex min-h-svh flex-col">
\t\t\t<AppHeader />
\t\t\t<main class="flex-1 overflow-y-auto p-4 pb-20">{@render children()}</main>
\t\t\t<BottomNav />
\t\t</div>
\t{:else if ui.isMedium}
\t\t<div class="flex min-h-svh">
\t\t\t<AppSidebar forceCollapsed />
\t\t\t<div class="flex flex-1 flex-col min-w-0">
\t\t\t\t<AppHeader />
\t\t\t\t<main class="flex-1 overflow-y-auto p-4">{@render children()}</main>
\t\t\t</div>
\t\t</div>
\t{:else}
\t\t<div
\t\t\tclass="group/sidebar-wrapper flex min-h-svh"
\t\t\tdata-sidebar-state={ui.sidebarCollapsed ? 'collapsed' : 'expanded'}
\t\t>
\t\t\t<AppSidebar />
\t\t\t<div class="flex flex-1 flex-col min-w-0">
\t\t\t\t<AppHeader />
\t\t\t\t<main class="flex-1 overflow-y-auto p-4">{@render children()}</main>
\t\t\t</div>
\t\t</div>
\t{/if}
{/if}
"""
