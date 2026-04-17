import type { Component } from 'svelte';

import CanvasFallback from './CanvasFallback.svelte';
import CodeViewer from './CodeViewer.svelte';
import DataTable from './DataTable.svelte';
import DynamicForm from './DynamicForm.svelte';
import Report from './Report.svelte';
import WorkflowDiagram from './WorkflowDiagram.svelte';

export interface CanvasComponentEntry {
	component: Component<{
		activity: import('../chat.types').WorkspaceActivity;
		onAction?: (a: import('../chat.types').WorkspaceAction) => void;
	}>;
	label: string;
}

const registry = new Map<string, CanvasComponentEntry>();

export function registerCanvasComponent(activityType: string, entry: CanvasComponentEntry) {
	registry.set(activityType, entry);
}

export function resolveCanvasComponent(activityType: string): CanvasComponentEntry {
	return registry.get(activityType) ?? registry.get('fallback')!;
}

registerCanvasComponent('fallback', { component: CanvasFallback, label: 'Activity' });
registerCanvasComponent('dynamic_form', { component: DynamicForm, label: 'Form' });
registerCanvasComponent('data_table', { component: DataTable, label: 'Data Table' });
registerCanvasComponent('report', { component: Report, label: 'Report' });
registerCanvasComponent('workflow', { component: WorkflowDiagram, label: 'Workflow' });
registerCanvasComponent('code_viewer', { component: CodeViewer, label: 'Code' });
