import type { SaasLocale } from "../model"

const copy = {
  en: {
    title: "People & invitations",
    description: "Invite teammates and keep workspace access intentional.",
    inviteTitle: "Invite a teammate",
    email: "Email address",
    role: "Workspace role",
    admin: "Admin",
    member: "Member",
    owner: "Owner",
    send: "Send invitation",
    sending: "Sending…",
    pending: "Pending invitations",
    noInvitations: "No pending invitations.",
    active: "Workspace members",
    noMembers: "No active members.",
    revoke: "Revoke",
    remove: "Remove",
    loading: "Loading workspace access…",
    error: "Workspace access could not be loaded. Please try again.",
    ownerOnly: "Only workspace owners can manage member roles.",
    denied: "You do not have permission to manage this workspace.",
  },
  ru: {
    title: "Участники и приглашения",
    description: "Приглашайте коллег и контролируйте доступ к рабочему пространству.",
    inviteTitle: "Пригласить участника",
    email: "Адрес электронной почты",
    role: "Роль в пространстве",
    admin: "Администратор",
    member: "Участник",
    owner: "Владелец",
    send: "Отправить приглашение",
    sending: "Отправка…",
    pending: "Ожидающие приглашения",
    noInvitations: "Нет ожидающих приглашений.",
    active: "Участники пространства",
    noMembers: "Нет активных участников.",
    revoke: "Отозвать",
    remove: "Удалить",
    loading: "Загрузка доступа…",
    error: "Не удалось загрузить доступ. Повторите попытку.",
    ownerOnly: "Только владелец может изменять роли участников.",
    denied: "У вас нет прав для управления этим пространством.",
  },
} as const

export function getPeopleCopy(locale: SaasLocale): (typeof copy)[SaasLocale] {
  return copy[locale]
}
