import { z } from "zod"

import {
  AccountContextSchema,
  AccountIdSchema,
  UserIdSchema,
  WorkspaceContextSchema,
} from "../account/account-contracts"

export const CredentialsSchema = z
  .object({
    email: z.string().email().max(320),
    password: z.string().min(8).max(256),
  })
  .strict()

export const AuthSessionSchema = z
  .object({
    user_id: UserIdSchema,
    email: z.string().email(),
    accounts: z.array(AccountContextSchema).readonly(),
    active_account_id: AccountIdSchema.nullable(),
    workspace: WorkspaceContextSchema.nullable(),
  })
  .strict()

export const SignupOutcomeSchema = z
  .object({
    confirmation_required: z.boolean(),
  })
  .strict()

export type AuthSession = z.infer<typeof AuthSessionSchema>
export type Credentials = z.infer<typeof CredentialsSchema>
export type SignupOutcome = z.infer<typeof SignupOutcomeSchema>
