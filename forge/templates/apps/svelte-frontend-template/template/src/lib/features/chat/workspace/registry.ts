import type { Component } from 'svelte';

import ApprovalReview from './ApprovalReview.svelte';
import CredentialForm from './CredentialForm.svelte';
import FallbackActivity from './FallbackActivity.svelte';
import FileExplorer from './FileExplorer.svelte';
import UserPromptReview from './UserPromptReview.svelte';

export interface WorkspaceComponentEntry {
	component: Component<{ activity: import('../chat.types').WorkspaceActivity; onAction?: (a: import('../chat.types').WorkspaceAction) => void }>;
	label: string;
}

const registry = new Map<string, WorkspaceComponentEntry>();

export function registerWorkspaceComponent(activityType: string, entry: WorkspaceComponentEntry) {
	registry.set(activityType, entry);
}

export function resolveWorkspaceComponent(activityType: string): WorkspaceComponentEntry {
	return registry.get(activityType) ?? registry.get('fallback')!;
}

registerWorkspaceComponent('credential_form', { component: CredentialForm, label: 'Credential Form' });
registerWorkspaceComponent('file_explorer', { component: FileExplorer, label: 'File Explorer' });
registerWorkspaceComponent('approval_review', { component: ApprovalReview, label: 'Review & Approve' });
registerWorkspaceComponent('user_prompt', { component: UserPromptReview, label: 'Question' });
registerWorkspaceComponent('fallback', { component: FallbackActivity, label: 'Activity' });
