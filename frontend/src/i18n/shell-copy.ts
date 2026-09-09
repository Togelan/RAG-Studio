import type { Locale } from "./locale-inventory"

export type ShellCopy = {
  readonly account: string
  readonly accountUnavailable: string
  readonly context: string
  readonly contextError: string
  readonly contextForbidden: string
  readonly contextLoading: string
  readonly contextPending: string
  readonly contextRevoked: string
  readonly healthDegraded: string
  readonly noContext: string
  readonly personalLab: string
  readonly roleAdmin: string
  readonly roleMember: string
  readonly roleOwner: string
  readonly signOut: string
  readonly signIn: string
  readonly signedInAs: string
  readonly selectAvailableContext: string
}

const shellCopyByLocale = {
  en: {
    account: "Account",
    accountUnavailable: "Account unavailable",
    context: "Context",
    contextError: "Context is temporarily unavailable. Choose another available context.",
    contextForbidden: "You no longer have access to this context. Choose an available context.",
    contextLoading: "Loading confirmed context",
    contextPending: "Updating context",
    contextRevoked: "This context is no longer available. Choose an available context.",
    healthDegraded: "Degraded",
    noContext: "No context is available yet.",
    personalLab: "Personal Lab",
    roleAdmin: "Admin",
    roleMember: "Member",
    roleOwner: "Owner",
    signOut: "Sign out",
    signIn: "Sign in",
    signedInAs: "Signed in as",
    selectAvailableContext: "Select an available context",
  },
  ru: {
    account: "Аккаунт",
    accountUnavailable: "Аккаунт недоступен",
    context: "Контекст",
    contextError: "Контекст временно недоступен. Выберите другой доступный контекст.",
    contextForbidden: "У вас больше нет доступа к этому контексту. Выберите доступный контекст.",
    contextLoading: "Загрузка подтверждённого контекста",
    contextPending: "Обновление контекста",
    contextRevoked: "Этот контекст больше недоступен. Выберите доступный контекст.",
    healthDegraded: "Сниженная доступность",
    noContext: "Доступный контекст пока отсутствует.",
    personalLab: "Личная лаборатория",
    roleAdmin: "Администратор",
    roleMember: "Участник",
    roleOwner: "Владелец",
    signOut: "Выйти",
    signIn: "Войти",
    signedInAs: "Выполнен вход:",
    selectAvailableContext: "Выберите доступный контекст",
  },
} as const satisfies Readonly<Record<Locale, ShellCopy>>

export type EffectiveRole = "owner" | "admin" | "member"

export function getShellCopy(locale: Locale): ShellCopy {
  return shellCopyByLocale[locale]
}

export function effectiveRoleLabel(locale: Locale, role: EffectiveRole): string {
  const copy = getShellCopy(locale)
  switch (role) {
    case "owner":
      return copy.roleOwner
    case "admin":
      return copy.roleAdmin
    case "member":
      return copy.roleMember
  }
}
