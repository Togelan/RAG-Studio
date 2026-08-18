import { z } from "zod"

import { type ApiClient, apiClient } from "../../../api/client"

export const chatbotStatuses = ["enabled", "disabled", "archived"] as const

const LocalizedNameSchema = z.object({
  en: z.string().min(1).max(120),
  ru: z.string().min(1).max(120),
})

const LocalizedInstructionsSchema = z.object({
  en: z.string().max(8_000),
  ru: z.string().max(8_000),
})

const ChatbotRecordSchema = z.object({
  id: z.string().uuid(),
  workspace_id: z.string().uuid(),
  name: LocalizedNameSchema,
  instructions: LocalizedInstructionsSchema,
  provider: z.string().min(1).max(40),
  model_name: z.string().min(1).max(120),
  source_scope: z.literal("workspace_all"),
  status: z.enum(chatbotStatuses),
  version: z.number().int().positive(),
})

export type ChatbotRecord = z.infer<typeof ChatbotRecordSchema>

export type ChatbotDefinitionInput = {
  readonly name: { readonly en: string; readonly ru: string }
  readonly instructions: { readonly en: string; readonly ru: string }
  readonly provider: string
  readonly model_name: string
  readonly source_scope: "workspace_all"
}

export type ChatbotUpdateInput = ChatbotDefinitionInput & { readonly version: number }

export type ChatbotGateway = {
  readonly list: (workspaceId: string) => Promise<readonly ChatbotRecord[]>
  readonly get: (workspaceId: string, chatbotId: string) => Promise<ChatbotRecord>
  readonly create: (workspaceId: string, input: ChatbotDefinitionInput) => Promise<ChatbotRecord>
  readonly update: (
    workspaceId: string,
    chatbotId: string,
    input: ChatbotUpdateInput,
  ) => Promise<ChatbotRecord>
  readonly disable: (
    workspaceId: string,
    chatbotId: string,
    version: number,
  ) => Promise<ChatbotRecord>
  readonly archive: (workspaceId: string, chatbotId: string, version: number) => Promise<void>
}

function chatbotsPath(workspaceId: string): string {
  return `/api/saas/workspaces/${encodeURIComponent(workspaceId)}/chatbots`
}

function chatbotPath(workspaceId: string, chatbotId: string): string {
  return `${chatbotsPath(workspaceId)}/${encodeURIComponent(chatbotId)}`
}

export function createChatbotGateway(client: ApiClient = apiClient): ChatbotGateway {
  return {
    list: (workspaceId) => client.get(chatbotsPath(workspaceId), z.array(ChatbotRecordSchema)),
    get: (workspaceId, chatbotId) =>
      client.get(chatbotPath(workspaceId, chatbotId), ChatbotRecordSchema),
    create: (workspaceId, input) =>
      client.post(chatbotsPath(workspaceId), input, ChatbotRecordSchema, {
        headers: { "Idempotency-Key": `chatbot-${crypto.randomUUID()}` },
      }),
    update: (workspaceId, chatbotId, input) =>
      client.patch(chatbotPath(workspaceId, chatbotId), input, ChatbotRecordSchema),
    disable: (workspaceId, chatbotId, version) =>
      client.post(
        `${chatbotPath(workspaceId, chatbotId)}/disable`,
        { version },
        ChatbotRecordSchema,
      ),
    archive: (workspaceId, chatbotId, version) =>
      client.delete(chatbotPath(workspaceId, chatbotId), z.undefined(), {
        body: { version },
      }),
  }
}
