import type { AuthMode, SaasLocale, WorkspaceRole } from "./model"

type SaasCopy = {
  readonly activeWorkspace: string
  readonly admin: string
  readonly authError: string
  readonly chatbots: string
  readonly confirmationRequired: string
  readonly createWorkspace: string
  readonly email: string
  readonly member: string
  readonly navigation: string
  readonly owner: string
  readonly password: string
  readonly people: string
  readonly productLabel: string
  readonly signIn: string
  readonly signInPrompt: string
  readonly signOut: string
  readonly signUp: string
  readonly signUpPrompt: string
  readonly sources: string
  readonly startWorkspace: string
  readonly submitting: string
  readonly workspaceName: string
  readonly workspaceReady: string
}

const copy = {
  en: {
    activeWorkspace: "Active workspace",
    admin: "Admin",
    authError: "Sign in could not be completed. Please try again.",
    chatbots: "Chatbots",
    confirmationRequired: "Check your inbox to confirm the account, then sign in.",
    createWorkspace: "Create workspace",
    email: "Email",
    member: "Member",
    navigation: "Navigation",
    owner: "Owner",
    password: "Password",
    people: "People & invitations",
    productLabel: "RAG-Studio workspace",
    signIn: "Sign in",
    signInPrompt: "New to RAG-Studio?",
    signOut: "Sign out",
    signUp: "Create account",
    signUpPrompt: "Already have an account?",
    sources: "Sources",
    startWorkspace: "Start a trusted workspace",
    submitting: "Please wait",
    workspaceName: "Workspace name",
    workspaceReady: "Your authenticated workspace context is ready.",
  },
  ru: {
    activeWorkspace: "Активное пространство",
    admin: "Администратор",
    authError: "Не удалось войти. Повторите попытку.",
    chatbots: "Чат-боты",
    confirmationRequired: "Подтвердите аккаунт по письму, затем войдите.",
    createWorkspace: "Создать пространство",
    email: "Электронная почта",
    member: "Участник",
    navigation: "Навигация",
    owner: "Владелец",
    password: "Пароль",
    people: "Люди и приглашения",
    productLabel: "Рабочее пространство RAG-Studio",
    signIn: "Войти",
    signInPrompt: "Впервые в RAG-Studio?",
    signOut: "Выйти",
    signUp: "Создать аккаунт",
    signUpPrompt: "Уже есть аккаунт?",
    sources: "Источники",
    startWorkspace: "Создайте надёжное пространство",
    submitting: "Подождите",
    workspaceName: "Название пространства",
    workspaceReady: "Контекст рабочего пространства подтверждён.",
  },
} satisfies Readonly<Record<SaasLocale, SaasCopy>>

export function getSaasCopy(locale: SaasLocale): SaasCopy {
  return copy[locale]
}

export function authActionLabel(locale: SaasLocale, mode: AuthMode): string {
  const value = getSaasCopy(locale)
  return mode === "sign-in" ? value.signIn : value.signUp
}

export function roleLabel(locale: SaasLocale, role: WorkspaceRole): string {
  const value = getSaasCopy(locale)
  switch (role) {
    case "owner":
      return value.owner
    case "admin":
      return value.admin
    case "member":
      return value.member
  }
}
