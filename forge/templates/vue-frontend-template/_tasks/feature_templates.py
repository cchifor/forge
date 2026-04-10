"""Vue/TypeScript code templates for dynamic feature generation."""

from __future__ import annotations


def make_feature_context(plural_name: str) -> dict[str, str]:
    """Derive all naming variants from a plural feature name."""
    singular = (
        plural_name.rstrip("s")
        if plural_name.endswith("s") and len(plural_name) > 1
        else plural_name
    )
    return {
        "plural": plural_name,
        "singular": singular,
        "Plural": plural_name[0].upper() + plural_name[1:],
        "Singular": singular[0].upper() + singular[1:],
        "PLURAL": plural_name.upper(),
    }


# ──────────────────────────────────────────────
# index.ts -- barrel export with route definitions
# ──────────────────────────────────────────────
INDEX_TEMPLATE = """\
export {{ use{Plural}, use{Singular}, useCreate{Singular}, useUpdate{Singular}, useDelete{Singular} }} from './api/use{Plural}'
export {{ {singular}Schema, paginated{Singular}ResponseSchema }} from './model/{singular}.schema'
export type {{ {Singular}Parsed }} from './model/{singular}.schema'

export const {plural}Routes = [
  {{
    path: '{plural}',
    name: '{plural}',
    component: () => import('./ui/{Plural}ListPage.vue'),
    meta: {{ title: '{Plural}' }},
  }},
  {{
    path: '{plural}/new',
    name: '{singular}-create',
    component: () => import('./ui/{Singular}CreatePage.vue'),
    meta: {{ title: 'New {Singular}' }},
  }},
  {{
    path: '{plural}/:{singular}Id',
    name: '{singular}-detail',
    component: () => import('./ui/{Singular}DetailPage.vue'),
    props: true,
    meta: {{ title: '{Singular} Detail' }},
  }},
]
"""

# ──────────────────────────────────────────────
# api/use{Plural}.ts -- Vue Query CRUD composables
# ──────────────────────────────────────────────
API_COMPOSABLE_TEMPLATE = """\
import {{ useQuery, useMutation, useQueryClient }} from '@tanstack/vue-query'
import type {{ Ref }} from 'vue'
import {{ computed }} from 'vue'
import {{ useApiClient }} from '@/shared/composables/useApiClient'
import {{ paginated{Singular}ResponseSchema, {singular}Schema }} from '../model/{singular}.schema'

function unref<T>(val: Ref<T> | T): T {{
  return (val as Ref<T>)?.value !== undefined ? (val as Ref<T>).value : (val as T)
}}

export function use{Plural}(params: {{
  skip?: Ref<number> | number
  limit?: Ref<number> | number
  search?: Ref<string | undefined> | string
}} = {{}}) {{
  const client = useApiClient()

  const queryKey = computed(() => [
    '{plural}',
    {{
      skip: unref(params.skip) ?? 0,
      limit: unref(params.limit) ?? 50,
      search: unref(params.search),
    }},
  ])

  return useQuery({{
    queryKey,
    queryFn: async () => {{
      const searchParams = new URLSearchParams()
      const skip = unref(params.skip)
      const limit = unref(params.limit)
      const search = unref(params.search)

      if (skip != null) searchParams.set('skip', String(skip))
      if (limit != null) searchParams.set('limit', String(limit))
      if (search) searchParams.set('search', search)

      const raw = await client.get('api/{backend_name}/v1/{plural}', {{ searchParams }}).json()
      return paginated{Singular}ResponseSchema.parse(raw)
    }},
    placeholderData: (prev) => prev,
  }})
}}

export function use{Singular}(id: Ref<string> | string) {{
  const client = useApiClient()

  return useQuery({{
    queryKey: computed(() => ['{plural}', unref(id)]),
    queryFn: async () => {{
      const raw = await client.get(`api/{backend_name}/v1/{plural}/${{unref(id)}}`).json()
      return {singular}Schema.parse(raw)
    }},
    enabled: computed(() => !!unref(id)),
  }})
}}

export function useCreate{Singular}() {{
  const client = useApiClient()
  const queryClient = useQueryClient()

  return useMutation({{
    mutationFn: async (data: Record<string, unknown>) => {{
      const raw = await client.post('api/{backend_name}/v1/{plural}', {{ json: data }}).json()
      return {singular}Schema.parse(raw)
    }},
    onSuccess: () => {{
      queryClient.invalidateQueries({{ queryKey: ['{plural}'] }})
    }},
  }})
}}

export function useUpdate{Singular}() {{
  const client = useApiClient()
  const queryClient = useQueryClient()

  return useMutation({{
    mutationFn: async ({{ id, data }}: {{ id: string; data: Record<string, unknown> }}) => {{
      const raw = await client.patch(`api/{backend_name}/v1/{plural}/${{id}}`, {{ json: data }}).json()
      return {singular}Schema.parse(raw)
    }},
    onSuccess: (_data, variables) => {{
      queryClient.invalidateQueries({{ queryKey: ['{plural}'] }})
      queryClient.invalidateQueries({{ queryKey: ['{plural}', variables.id] }})
    }},
  }})
}}

export function useDelete{Singular}() {{
  const client = useApiClient()
  const queryClient = useQueryClient()

  return useMutation({{
    mutationFn: async (id: string) => {{
      await client.delete(`api/{backend_name}/v1/{plural}/${{id}}`)
    }},
    onSuccess: () => {{
      queryClient.invalidateQueries({{ queryKey: ['{plural}'] }})
    }},
  }})
}}
"""

# ──────────────────────────────────────────────
# model/{singular}.schema.ts -- Zod schemas
# ──────────────────────────────────────────────
SCHEMA_TEMPLATE = """\
import {{ z }} from 'zod'
import {{ paginatedResponseSchema }} from '@/shared/api/schemas/common.schema'

export const {singular}Schema = z.object({{
  id: z.string().uuid(),
  name: z.string(),
  description: z.string().nullable(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
}})

export const paginated{Singular}ResponseSchema = paginatedResponseSchema({singular}Schema)

export type {Singular}Parsed = z.infer<typeof {singular}Schema>
export type Paginated{Singular}ResponseParsed = z.infer<typeof paginated{Singular}ResponseSchema>
"""

# ──────────────────────────────────────────────
# model/{singular}.schema.test.ts
# ──────────────────────────────────────────────
SCHEMA_TEST_TEMPLATE = """\
import {{ describe, it, expect }} from 'vitest'
import {{ {singular}Schema, paginated{Singular}ResponseSchema }} from './{singular}.schema'

describe('{singular}Schema', () => {{
  const valid{Singular} = {{
    id: '00000000-0000-0000-0000-000000000001',
    name: 'Test {Singular}',
    description: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
  }}

  it('parses a valid {singular}', () => {{
    const result = {singular}Schema.parse(valid{Singular})
    expect(result.id).toBe(valid{Singular}.id)
    expect(result.name).toBe('Test {Singular}')
  }})

  it('rejects {singular} with missing name', () => {{
    const {{ name: _, ...invalid }} = valid{Singular}
    expect(() => {singular}Schema.parse(invalid)).toThrow()
  }})
}})

describe('paginated{Singular}ResponseSchema', () => {{
  it('parses a valid paginated response', () => {{
    const response = {{
      items: [{{
        id: '00000000-0000-0000-0000-000000000001',
        name: '{Singular}',
        description: null,
        created_at: null,
        updated_at: null,
      }}],
      total: 1,
      skip: 0,
      limit: 50,
      has_more: false,
    }}
    const result = paginated{Singular}ResponseSchema.parse(response)
    expect(result.items).toHaveLength(1)
    expect(result.has_more).toBe(false)
  }})
}})
"""

# ──────────────────────────────────────────────
# ui/{Plural}ListPage.vue
# ──────────────────────────────────────────────
LIST_PAGE_TEMPLATE = """\
<script setup lang="ts">
import {{ ref, computed, watch }} from 'vue'
import {{ useRouter }} from 'vue-router'
import {{ Plus, Search, X, Trash2, Eye, MoreHorizontal, Package }} from 'lucide-vue-next'
import {{ toast }} from 'vue-sonner'
import {{ Card, CardContent }} from '@/shared/ui/card'
import {{ Button }} from '@/shared/ui/button'
import {{ Input }} from '@/shared/ui/input'
import {{ Badge }} from '@/shared/ui/badge'
import {{ Skeleton }} from '@/shared/ui/skeleton'
import {{
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
}} from '@/shared/ui/dropdown-menu'
import ConfirmDialog from '@/shared/components/ConfirmDialog.vue'
import EmptyState from '@/shared/components/EmptyState.vue'
import {{ use{Plural}, useDelete{Singular} }} from '@/features/{plural}'

const router = useRouter()

const page = ref(0)
const pageSize = ref(20)
const searchInput = ref('')
const searchQuery = ref('')

let searchTimeout: ReturnType<typeof setTimeout>
watch(searchInput, (val) => {{
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {{
    searchQuery.value = val
    page.value = 0
  }}, 300)
}})

const skip = computed(() => page.value * pageSize.value)

const {{ data, isLoading, isError }} = use{Plural}({{
  skip,
  limit: pageSize,
  search: searchQuery,
}})

const delete{Singular} = useDelete{Singular}()
const deleteDialogOpen = ref(false)
const {singular}ToDelete = ref<{{ id: string; name: string }} | null>(null)

function confirmDelete({singular}: {{ id: string; name: string }}) {{
  {singular}ToDelete.value = {singular}
  deleteDialogOpen.value = true
}}

async function handleDelete() {{
  if (!{singular}ToDelete.value) return
  try {{
    await delete{Singular}.mutateAsync({singular}ToDelete.value.id)
    toast.success(`{Singular} "${{{singular}ToDelete.value.name}}" deleted`)
  }} catch {{
    // handled by global mutation onError
  }}
  {singular}ToDelete.value = null
}}

function formatDate(dateStr: string | null): string {{
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleDateString(undefined, {{
    year: 'numeric', month: 'short', day: 'numeric',
  }})
}}
</script>

<template>
  <div class="space-y-4" data-test="{plural}-list">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">{Plural}</h1>
        <p class="text-muted-foreground">Manage your {plural}</p>
      </div>
      <Button data-test="{plural}-create-btn" @click="router.push('/{plural}/new')">
        <Plus class="mr-2 h-4 w-4" />
        New {Singular}
      </Button>
    </div>

    <!-- Search -->
    <div class="relative max-w-sm">
      <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
      <Input v-model="searchInput" data-test="{plural}-search-input" placeholder="Search {plural}..." class="pl-8" />
      <button
        v-if="searchInput"
        class="absolute right-2.5 top-2.5 text-muted-foreground hover:text-foreground"
        @click="searchInput = ''"
      >
        <X class="h-4 w-4" />
      </button>
    </div>

    <!-- Loading -->
    <div v-if="isLoading" class="space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-24 w-full rounded-xl" />
    </div>

    <!-- Error -->
    <div v-else-if="isError" class="text-center text-muted-foreground py-8">
      Failed to load {plural}. Please try again.
    </div>

    <!-- Empty -->
    <EmptyState
      v-else-if="data && data.items.length === 0"
      message="No {plural} found."
      :icon="Package"
    >
      <template #action>
        <Button @click="router.push('/{plural}/new')">Create your first {singular}</Button>
      </template>
    </EmptyState>

    <!-- Card list -->
    <div v-else-if="data" class="space-y-3">
      <Card
        v-for="{singular} in data.items"
        :key="{singular}.id"
        data-test="{singular}-card"
        class="interactive-press cursor-pointer"
        @click="router.push(`/{plural}/${{{singular}.id}}`)"
      >
        <CardContent class="p-4">
          <div class="flex items-center justify-between">
            <span class="font-medium" data-test="{singular}-name">{{{{ {singular}.name }}}}</span>
            <div class="flex items-center gap-2" @click.stop>
              <DropdownMenu>
                <DropdownMenuTrigger as-child>
                  <Button variant="ghost" size="icon" class="h-8 w-8">
                    <MoreHorizontal class="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem @click="router.push(`/{plural}/${{{singular}.id}}`)">
                    <Eye class="mr-2 h-4 w-4" />
                    View
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    class="text-destructive"
                    data-test="{singular}-delete-btn"
                    @click="confirmDelete({{ id: {singular}.id, name: {singular}.name }})"
                  >
                    <Trash2 class="mr-2 h-4 w-4" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
          <p v-if="{singular}.description" class="mt-1 text-sm text-muted-foreground line-clamp-2">
            {{{{ {singular}.description }}}}
          </p>
        </CardContent>
      </Card>
    </div>

    <!-- Pagination -->
    <div v-if="data && data.total > 0" class="flex items-center justify-between text-sm text-muted-foreground">
      <p>Showing {{{{ data.skip + 1 }}}}-{{{{ Math.min(data.skip + data.limit, data.total) }}}} of {{{{ data.total }}}}</p>
      <Button v-if="data.has_more" data-test="{plural}-load-more" variant="outline" size="sm" @click="page++">
        Load More
      </Button>
    </div>

    <ConfirmDialog
      v-model:open="deleteDialogOpen"
      title="Delete {Singular}"
      :description="`Are you sure you want to delete '${{ {singular}ToDelete?.name }}'?`"
      confirm-label="Delete"
      @confirm="handleDelete"
    />
  </div>
</template>
"""

# ──────────────────────────────────────────────
# ui/{Singular}CreatePage.vue
# ──────────────────────────────────────────────
CREATE_PAGE_TEMPLATE = """\
<script setup lang="ts">
import {{ ref }} from 'vue'
import {{ useRouter }} from 'vue-router'
import {{ ArrowLeft, Loader2 }} from 'lucide-vue-next'
import {{ toast }} from 'vue-sonner'
import {{ Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter }} from '@/shared/ui/card'
import {{ Button }} from '@/shared/ui/button'
import {{ Input }} from '@/shared/ui/input'
import {{ Label }} from '@/shared/ui/label'
import {{ Textarea }} from '@/shared/ui/textarea'
import {{ useCreate{Singular} }} from '@/features/{plural}'

const router = useRouter()
const create{Singular} = useCreate{Singular}()

const name = ref('')
const description = ref('')

function handleSubmit() {{
  if (!name.value.trim()) {{
    toast.error('Name is required')
    return
  }}

  create{Singular}.mutate(
    {{
      name: name.value.trim(),
      description: description.value.trim() || undefined,
    }},
    {{
      onSuccess: ({singular}) => {{
        toast.success(`{Singular} "${{ {singular}.name }}" created`)
        router.push(`/{plural}/${{ {singular}.id }}`)
      }},
    }},
  )
}}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-2">
      <Button variant="ghost" size="icon" @click="router.push('/{plural}')">
        <ArrowLeft class="h-4 w-4" />
      </Button>
      <div>
        <h1 class="text-3xl font-bold tracking-tight">New {Singular}</h1>
        <p class="text-muted-foreground">Create a new {singular}</p>
      </div>
    </div>

    <Card class="max-w-2xl">
      <CardHeader>
        <CardTitle>{Singular} Details</CardTitle>
        <CardDescription>Fill in the details</CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="space-y-2">
          <Label for="name">Name *</Label>
          <Input id="name" v-model="name" data-test="{singular}-name-input" placeholder="Enter name" required />
        </div>
        <div class="space-y-2">
          <Label for="description">Description</Label>
          <Textarea id="description" v-model="description" data-test="{singular}-description-input" placeholder="Enter description" :rows="3" />
        </div>
      </CardContent>
      <CardFooter class="gap-2">
        <Button variant="outline" data-test="{singular}-cancel-btn" @click="router.push('/{plural}')">Cancel</Button>
        <Button data-test="{singular}-submit-btn" :disabled="create{Singular}.isPending.value" @click="handleSubmit">
          <Loader2 v-if="create{Singular}.isPending.value" class="mr-2 h-4 w-4 animate-spin" />
          {{{{ create{Singular}.isPending.value ? 'Creating...' : 'Create {Singular}' }}}}
        </Button>
      </CardFooter>
    </Card>
  </div>
</template>
"""

# ──────────────────────────────────────────────
# ui/{Singular}DetailPage.vue
# ──────────────────────────────────────────────
DETAIL_PAGE_TEMPLATE = """\
<script setup lang="ts">
import {{ ref, watch }} from 'vue'
import {{ useRouter }} from 'vue-router'
import {{ ArrowLeft, Pencil, Trash2, Save, X, Loader2 }} from 'lucide-vue-next'
import {{ toast }} from 'vue-sonner'
import {{ Card, CardHeader, CardTitle, CardContent, CardFooter }} from '@/shared/ui/card'
import {{ Button }} from '@/shared/ui/button'
import {{ Input }} from '@/shared/ui/input'
import {{ Label }} from '@/shared/ui/label'
import {{ Textarea }} from '@/shared/ui/textarea'
import {{ Skeleton }} from '@/shared/ui/skeleton'
import ConfirmDialog from '@/shared/components/ConfirmDialog.vue'
import {{ use{Singular}, useUpdate{Singular}, useDelete{Singular} }} from '@/features/{plural}'

const props = defineProps<{{ {singular}Id: string }}>()
const router = useRouter()

const {{ data: {singular}, isLoading, isError }} = use{Singular}(props.{singular}Id)
const update{Singular} = useUpdate{Singular}()
const delete{Singular} = useDelete{Singular}()

const editing = ref(false)
const editName = ref('')
const editDescription = ref('')
const deleteDialogOpen = ref(false)

watch({singular}, (val) => {{
  if (val) {{
    editName.value = val.name
    editDescription.value = val.description ?? ''
  }}
}}, {{ immediate: true }})

function startEdit() {{ editing.value = true }}

function cancelEdit() {{
  if ({singular}.value) {{
    editName.value = {singular}.value.name
    editDescription.value = {singular}.value.description ?? ''
  }}
  editing.value = false
}}

function saveEdit() {{
  if (!editName.value.trim()) {{
    toast.error('Name is required')
    return
  }}
  update{Singular}.mutate(
    {{ id: props.{singular}Id, data: {{ name: editName.value.trim(), description: editDescription.value.trim() || null }} }},
    {{ onSuccess: () => {{ toast.success('{Singular} updated'); editing.value = false }} }},
  )
}}

async function handleDelete() {{
  try {{
    await delete{Singular}.mutateAsync(props.{singular}Id)
    toast.success('{Singular} deleted')
    router.push('/{plural}')
  }} catch {{}}
}}

function formatDate(dateStr: string | null): string {{
  if (!dateStr) return 'N/A'
  return new Date(dateStr).toLocaleString()
}}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-2">
      <Button variant="ghost" size="icon" @click="router.push('/{plural}')">
        <ArrowLeft class="h-4 w-4" />
      </Button>
      <div class="flex-1">
        <h1 class="text-3xl font-bold tracking-tight">{Singular} Detail</h1>
      </div>
      <template v-if="{singular} && !editing">
        <Button variant="outline" data-test="{singular}-edit-btn" @click="startEdit"><Pencil class="mr-2 h-4 w-4" />Edit</Button>
        <Button variant="destructive" data-test="{singular}-delete-btn" @click="deleteDialogOpen = true"><Trash2 class="mr-2 h-4 w-4" />Delete</Button>
      </template>
    </div>

    <Card v-if="isLoading"><CardContent class="space-y-4 pt-6"><Skeleton class="h-8 w-48" /><Skeleton class="h-4 w-full" /></CardContent></Card>
    <Card v-else-if="isError"><CardContent class="pt-6 text-center text-muted-foreground">Failed to load.</CardContent></Card>

    <Card v-else-if="{singular} && !editing" data-test="{singular}-detail" class="max-w-2xl">
      <CardHeader><CardTitle>Summary</CardTitle></CardHeader>
      <CardContent>
        <dl class="space-y-3">
          <div><dt class="text-xs text-muted-foreground">Name</dt><dd class="text-sm font-medium">{{{{ {singular}.name }}}}</dd></div>
          <div><dt class="text-xs text-muted-foreground">Description</dt><dd class="text-sm">{{{{ {singular}.description || 'No description' }}}}</dd></div>
          <div class="grid grid-cols-2 gap-4">
            <div><dt class="text-xs text-muted-foreground">Created</dt><dd class="text-sm">{{{{ formatDate({singular}.created_at) }}}}</dd></div>
            <div><dt class="text-xs text-muted-foreground">Updated</dt><dd class="text-sm">{{{{ formatDate({singular}.updated_at) }}}}</dd></div>
          </div>
        </dl>
      </CardContent>
    </Card>

    <Card v-else-if="{singular} && editing" class="max-w-2xl">
      <CardHeader><CardTitle>Edit {Singular}</CardTitle></CardHeader>
      <CardContent>
        <form class="space-y-4" @submit.prevent="saveEdit">
          <div class="space-y-2"><Label>Name *</Label><Input v-model="editName" data-test="{singular}-edit-name-input" required /></div>
          <div class="space-y-2"><Label>Description</Label><Textarea v-model="editDescription" :rows="3" /></div>
        </form>
      </CardContent>
      <CardFooter class="gap-2">
        <Button variant="outline" data-test="{singular}-cancel-edit-btn" @click="cancelEdit"><X class="mr-2 h-4 w-4" />Cancel</Button>
        <Button data-test="{singular}-save-btn" :disabled="update{Singular}.isPending.value" @click="saveEdit">
          <Loader2 v-if="update{Singular}.isPending.value" class="mr-2 h-4 w-4 animate-spin" />
          <Save v-else class="mr-2 h-4 w-4" />
          {{{{ update{Singular}.isPending.value ? 'Saving...' : 'Save' }}}}
        </Button>
      </CardFooter>
    </Card>

    <ConfirmDialog
      v-model:open="deleteDialogOpen"
      title="Delete {Singular}"
      :description="`Are you sure you want to delete '${{ {singular}?.name }}'?`"
      confirm-label="Delete"
      @confirm="handleDelete"
    />
  </div>
</template>
"""

# ──────────────────────────────────────────────
# MSW handlers for a feature
# ──────────────────────────────────────────────
MSW_HANDLERS_TEMPLATE = """\
import {{ http, HttpResponse }} from 'msw'

const mock{Plural} = [
  {{
    id: '00000000-0000-0000-0000-000000000010',
    name: 'Test {Singular} 1',
    description: 'First test {singular}',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
  }},
  {{
    id: '00000000-0000-0000-0000-000000000020',
    name: 'Test {Singular} 2',
    description: null,
    created_at: '2026-02-01T00:00:00Z',
    updated_at: null,
  }},
]

export const {plural}Handlers = [
  http.get('*/api/v1/{plural}', ({{ request }}) => {{
    const url = new URL(request.url)
    const skip = parseInt(url.searchParams.get('skip') ?? '0')
    const limit = parseInt(url.searchParams.get('limit') ?? '50')
    const search = url.searchParams.get('search')

    let filtered = [...mock{Plural}]
    if (search)
      filtered = filtered.filter((i) =>
        i.name.toLowerCase().includes(search.toLowerCase()),
      )

    const paged = filtered.slice(skip, skip + limit)
    return HttpResponse.json({{
      items: paged,
      total: filtered.length,
      skip,
      limit,
      has_more: skip + limit < filtered.length,
    }})
  }}),

  http.get('*/api/v1/{plural}/:id', ({{ params }}) => {{
    const item = mock{Plural}.find((i) => i.id === params.id)
    if (!item)
      return HttpResponse.json(
        {{ message: 'Not found', type: 'NotFoundError', detail: null }},
        {{ status: 404 }},
      )
    return HttpResponse.json(item)
  }}),

  http.post('*/api/v1/{plural}', async ({{ request }}) => {{
    const body = (await request.json()) as Record<string, unknown>
    return HttpResponse.json(
      {{
        id: '00000000-0000-0000-0000-000000000099',
        name: body.name,
        description: body.description ?? null,
        created_at: new Date().toISOString(),
        updated_at: null,
      }},
      {{ status: 201 }},
    )
  }}),

  http.patch('*/api/v1/{plural}/:id', async ({{ params, request }}) => {{
    const body = (await request.json()) as Record<string, unknown>
    const item = mock{Plural}.find((i) => i.id === params.id)
    if (!item)
      return HttpResponse.json(
        {{ message: 'Not found', type: 'NotFoundError', detail: null }},
        {{ status: 404 }},
      )
    return HttpResponse.json({{ ...item, ...body }})
  }}),

  http.delete('*/api/v1/{plural}/:id', ({{ params }}) => {{
    const item = mock{Plural}.find((i) => i.id === params.id)
    if (!item)
      return HttpResponse.json(
        {{ message: 'Not found', type: 'NotFoundError', detail: null }},
        {{ status: 404 }},
      )
    return new HttpResponse(null, {{ status: 204 }})
  }}),
]
"""

# ──────────────────────────────────────────────
# Hub injection snippets
# ──────────────────────────────────────────────
HUB_ROUTER_IMPORT = "import {{ {plural}Routes }} from '@/features/{plural}'\n"
HUB_ROUTER_ROUTE = "      ...{plural}Routes,\n"
HUB_SIDEBAR_NAV = "  {{ title: '{Plural}', url: '/{plural}', icon: Package }},\n"
HUB_MSW_IMPORT = "import {{ {plural}Handlers }} from './{plural}.handlers'\n"
HUB_MSW_SPREAD = "  ...{plural}Handlers,\n"
