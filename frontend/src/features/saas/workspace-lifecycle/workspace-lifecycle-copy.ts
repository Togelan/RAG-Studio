import type { SaasLocale } from "../model"

const copy = {
  en: {
    accept: "Accept invitation",
    acceptDescription: "Join the workspace that invited this account.",
    accepted: "Invitation accepted. Your workspace is ready.",
    archive: "Archive workspace",
    archiveBody: (workspaceName: string) =>
      `Archive “${workspaceName}”? This ends access for every member and clears this workspace from this browser.`,
    archiveTitle: "Archive this workspace?",
    cancel: "Cancel",
    confirmArchive: "Confirm archive",
    confirmTransfer: "Confirm transfer",
    invitationToken: "Invitation token",
    lifecycle: "Workspace lifecycle",
    lifecycleDescription: "Transfer ownership before archiving a workspace.",
    loadError: "Workspace members could not be loaded. Please try again.",
    mutationError: "The workspace change could not be completed. Please try again.",
    newOwner: "New owner",
    noEligibleMembers: "Invite an administrator or member before transferring ownership.",
    transfer: "Transfer ownership",
    transferBody: (userId: string) =>
      `Transfer ownership to ${userId}? This member becomes the only workspace owner.`,
    transferTitle: "Transfer workspace ownership?",
  },
  ru: {
    accept: "Принять приглашение",
    acceptDescription: "Присоединитесь к пространству, которое пригласило этот аккаунт.",
    accepted: "Приглашение принято. Пространство готово к работе.",
    archive: "Архивировать пространство",
    archiveBody: (workspaceName: string) =>
      `Архивировать «${workspaceName}»? Доступ всех участников будет закрыт, а пространство исчезнет из этого браузера.`,
    archiveTitle: "Архивировать это пространство?",
    cancel: "Отмена",
    confirmArchive: "Подтвердить архивацию",
    confirmTransfer: "Подтвердить передачу",
    invitationToken: "Токен приглашения",
    lifecycle: "Жизненный цикл пространства",
    lifecycleDescription: "Перед архивацией передайте право владения пространством.",
    loadError: "Не удалось загрузить участников пространства. Повторите попытку.",
    mutationError: "Не удалось изменить пространство. Повторите попытку.",
    newOwner: "Новый владелец",
    noEligibleMembers: "Пригласите администратора или участника перед передачей владения.",
    transfer: "Передать владение",
    transferBody: (userId: string) =>
      `Передать владение пользователю ${userId}? Этот участник станет единственным владельцем пространства.`,
    transferTitle: "Передать владение пространством?",
  },
} as const

export function getWorkspaceLifecycleCopy(locale: SaasLocale): (typeof copy)[SaasLocale] {
  return copy[locale]
}
