export class AppError extends Error {
	constructor(
		public statusCode: number,
		message: string,
	) {
		super(message);
		this.name = this.constructor.name;
	}
}

export class NotFoundError extends AppError {
	constructor(entity: string, id: string) {
		super(404, `${entity} '${id}' not found`);
	}
}

export class AlreadyExistsError extends AppError {
	constructor(entity: string, name: string) {
		super(409, `${entity} '${name}' already exists`);
	}
}

export class ValidationError extends AppError {
	constructor(message: string) {
		super(422, message);
	}
}
