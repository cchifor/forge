<script lang="ts">
  import { getUiStore } from '../../src/lib/features/shell/model/ui.svelte';
  export const store = getUiStore();
</script>
<p>{store.breakpoint}:{store.effectiveSidebarWidth}:{store.chatMode}</p>
