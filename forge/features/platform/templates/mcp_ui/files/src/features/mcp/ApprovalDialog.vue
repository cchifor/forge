<!--
  Approval dialog for MCP tool calls (Vue scaffold, Phase 3.4).

  Matches the three ApprovalMode values from the shared enum:
    * auto          — dialog auto-accepts (use sparingly)
    * prompt-once   — prompt the first time per tool, remember for session
    * prompt-every  — prompt every invocation

  Integrates with the ApprovalMode enum emitted by the codegen pipeline
  from forge/templates/_shared/domain/enums/approval_mode.yaml.
-->
<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  toolName: string
  server: string
  inputPreview: string
  defaultMode: 'auto' | 'prompt-once' | 'prompt-every'
}

const props = defineProps<Props>()
const emit = defineEmits<{
  approve: [remember: boolean]
  deny: []
}>()

const remember = ref(props.defaultMode !== 'prompt-every')

function approve() { emit('approve', remember.value) }
function deny() { emit('deny') }
</script>

<template>
  <div class="approval-dialog" role="dialog" aria-modal="true">
    <h3>Approve tool call?</h3>
    <p><strong>{{ props.server }} · {{ props.toolName }}</strong></p>
    <pre class="input-preview">{{ props.inputPreview }}</pre>
    <label>
      <input type="checkbox" v-model="remember" />
      Remember this choice for this session
    </label>
    <footer>
      <button type="button" class="deny" @click="deny">Deny</button>
      <button type="button" class="approve" @click="approve">Approve</button>
    </footer>
  </div>
</template>

<style scoped>
.approval-dialog { padding: 1rem; background: var(--surface, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 0.5rem; max-width: 32rem; }
.input-preview { padding: 0.5rem; background: var(--muted, #f3f4f6); border-radius: 0.25rem; font-family: ui-monospace, monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-word; max-height: 12rem; overflow: auto; }
footer { display: flex; gap: 0.5rem; justify-content: flex-end; margin-top: 1rem; }
.approve { background: var(--primary, #2563eb); color: white; padding: 0.5rem 1rem; border-radius: 0.25rem; border: none; }
.deny { background: transparent; border: 1px solid var(--border, #e5e7eb); padding: 0.5rem 1rem; border-radius: 0.25rem; }
</style>
