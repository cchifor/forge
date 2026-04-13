export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	timestamp: Date;
}

let messages = $state<ChatMessage[]>([]);
let isGenerating = $state(false);
let contextLabel = $state('General');

function simulateResponse(userContent: string) {
	isGenerating = true;
	setTimeout(() => {
		const reply: ChatMessage = {
			id: crypto.randomUUID(),
			role: 'assistant',
			content: `This is a placeholder response to: "${userContent.slice(0, 80)}${userContent.length > 80 ? '...' : ''}"`,
			timestamp: new Date()
		};
		messages = [...messages, reply];
		isGenerating = false;
	}, 1500);
}

export function getChatStore() {
	function addUserMessage(content: string) {
		const msg: ChatMessage = {
			id: crypto.randomUUID(),
			role: 'user',
			content,
			timestamp: new Date()
		};
		messages = [...messages, msg];
		simulateResponse(content);
	}

	function clearMessages() {
		messages = [];
	}

	function setContext(label: string) {
		contextLabel = label;
	}

	return {
		get messages() {
			return messages;
		},
		get isGenerating() {
			return isGenerating;
		},
		get contextLabel() {
			return contextLabel;
		},
		addUserMessage,
		clearMessages,
		setContext
	};
}
