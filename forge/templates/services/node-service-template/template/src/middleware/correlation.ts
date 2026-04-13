import type { FastifyReply, FastifyRequest } from "fastify";
import { v4 as uuidv4 } from "uuid";

declare module "fastify" {
	interface FastifyRequest {
		correlationId: string;
	}
}

export async function correlationHook(req: FastifyRequest, reply: FastifyReply) {
	const id = (req.headers["x-request-id"] as string) || uuidv4();
	req.correlationId = id;
	reply.header("x-request-id", id);
}
