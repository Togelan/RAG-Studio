import { z } from "zod"

export const AccountIdSchema = z.string().uuid().brand("AccountId")
export const WorkspaceIdSchema = z.string().uuid().brand("WorkspaceId")
export const UserIdSchema = z.string().uuid().brand("UserId")

export const WorkspaceRoleSchema = z.enum(["owner", "admin", "member"])

export const WorkspaceContextSchema = z
  .object({
    id: WorkspaceIdSchema,
    name: z.string().min(1).max(120).nullable().optional(),
    role: WorkspaceRoleSchema,
  })
  .strict()

export const AccountOwnerProjectionSchema = z
  .object({
    can_manage_billing: z.boolean(),
    can_view_limits: z.boolean(),
    can_view_plan: z.boolean(),
  })
  .strict()

export const AccountContextSchema = z
  .object({
    id: AccountIdSchema,
    label: z.string().min(1).max(120),
    owner: AccountOwnerProjectionSchema.nullable(),
    status: z.literal("active"),
    workspaces: z.array(WorkspaceContextSchema).readonly(),
  })
  .strict()

export const AccountListSchema = z.array(AccountContextSchema).readonly()

export type AccountContext = z.infer<typeof AccountContextSchema>
export type AccountId = z.infer<typeof AccountIdSchema>
export type WorkspaceContext = z.infer<typeof WorkspaceContextSchema>
export type WorkspaceId = z.infer<typeof WorkspaceIdSchema>
export type WorkspaceRole = z.infer<typeof WorkspaceRoleSchema>
