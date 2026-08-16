from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCALES_ROOT = PROJECT_ROOT / "src" / "api" / "locales"
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
PACKAGE_PATH = FRONTEND_ROOT / "package.json"
I18N_ROOT = FRONTEND_ROOT / "src" / "i18n"
REACT_INVENTORY_PATH = I18N_ROOT / "locale-inventory.json"
REACT_INVENTORY_CONTRACT_TEST_PATH = I18N_ROOT / "locale-inventory.contract.test.ts"
FEATURES_ROOT = FRONTEND_ROOT / "src" / "features"
SETTINGS_FORM_PATH = FEATURES_ROOT / "settings" / "SettingsForm.tsx"
INGESTION_PANEL_PATH = FEATURES_ROOT / "ingestion" / "IngestionPanel.tsx"
FEATURE_COMPONENT_ROOTS = tuple(
    FEATURES_ROOT / name for name in ("settings", "ingestion")
)
RUNTIME_DATA_EXPRESSIONS = (
    "DEFAULT_PROMPTS",
    "document.filename",
    "chunk.text",
    "upload.message",
)
NPM_COMMAND = "npm.cmd" if sys.platform == "win32" else "npm"


def _production_component_source(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.tsx"))
        if not path.name.endswith(".test.tsx")
    )


def _backend_locale(name: str) -> dict[str, str]:
    return json.loads((LOCALES_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def test_authoritative_en_and_ru_locale_keys_remain_in_exact_parity() -> None:
    en = _backend_locale("en")
    ru = _backend_locale("ru")

    assert set(en) == set(ru)
    assert en
    assert all(value.strip() for value in en.values())
    assert all(value.strip() for value in ru.values())


def test_chat_count_and_retry_templates_are_backend_owned() -> None:
    en = _backend_locale("en")
    ru = _backend_locale("ru")

    assert en["chat_session_message_count"] == "Messages: {count}"
    assert ru["chat_session_message_count"] == "Сообщений: {count}"
    assert en["chat_retry_after"] == "Please retry in {seconds} seconds."
    assert ru["chat_retry_after"] == "Повторите попытку через {seconds} с."


def test_all_chat_visible_copy_is_backend_owned() -> None:
    en = _backend_locale("en")
    ru = _backend_locale("ru")

    expected_en = {
        "chat_assistant": "RAG assistant",
        "chat_you": "You",
        "chat_composer_hint": "Enter to send · Shift+Enter for a new line",
        "chat_copy_answer": "Copy answer",
        "chat_copied": "Copied",
        "chat_helpful": "Helpful",
        "chat_not_helpful": "Not helpful",
        "chat_history": "Conversation history",
        "chat_inspect_source": "Inspect source",
        "chat_loading": "Loading conversations…",
        "chat_location_unavailable": "Location unavailable",
        "chat_page": "Page",
        "chat_response_complete": "Response complete",
        "chat_source": "Source",
        "chat_sources": "Sources",
        "chat_snippet_unavailable": "Snippet unavailable",
        "chat_feature_title": "Chat with your knowledge",
        "locale_update_unavailable": "Locale update unavailable",
    }
    expected_ru = {
        "chat_assistant": "RAG-ассистент",
        "chat_you": "Вы",
        "chat_composer_hint": "Enter — отправить · Shift+Enter — новая строка",
        "chat_copy_answer": "Копировать ответ",
        "chat_copied": "Скопировано",
        "chat_helpful": "Полезно",
        "chat_not_helpful": "Не помогло",
        "chat_history": "История диалога",
        "chat_inspect_source": "Открыть источник",
        "chat_loading": "Загрузка диалогов…",
        "chat_location_unavailable": "Место не указано",
        "chat_page": "Страница",
        "chat_response_complete": "Ответ готов",
        "chat_source": "Источник",
        "chat_sources": "Источники",
        "chat_snippet_unavailable": "Фрагмент недоступен",
        "chat_feature_title": "Чат с вашей базой знаний",
        "locale_update_unavailable": "Не удалось обновить язык",
    }

    assert {key: en[key] for key in expected_en} == expected_en
    assert {key: ru[key] for key in expected_ru} == expected_ru


def test_visible_settings_and_shell_copy_is_backend_owned() -> None:
    en = _backend_locale("en")
    ru = _backend_locale("ru")

    expected_en = {
        "nav_dashboard": "Dashboard",
        "nav_coming_soon": "Coming soon",
        "settings_workspace_eyebrow": "Configuration workspace",
        "settings_local_encrypted_status": "Local encrypted settings",
        "settings_provider_list_unavailable": "Provider list unavailable; safe defaults shown.",
        "settings_generation": "Generation",
        "settings_answer_behavior": "Answer behavior",
        "settings_index_behavior": "Index behavior",
        "settings_knowledge_index": "Knowledge index",
        "settings_observability": "Observability",
        "settings_model_connection": "Model connection",
        "settings_provider_coming_soon": "coming soon",
        "settings_stored_keys_helper": "Stored keys stay masked. Enter a value only when replacing the key.",
        "settings_all_changes_saved": "All changes saved",
        "settings_unsaved_changes": "Unsaved changes",
        "settings_upload_file_types_helper": "TXT, MD, PDF, DOCX or CSV · 50 MB each · {count} files per batch",
        "settings_unavailable": "Settings are temporarily unavailable. Please try again.",
        "settings_loading": "Loading settings",
        "settings_discard_changes": "Discard changes",
        "settings_cached_model_list": "Cached model list",
        "ingestion_file_type_unknown": "File",
        "ingestion_hide_chunks": "Hide",
        "ingestion_loading_chunks": "Loading chunks…",
        "ingestion_chunk_preview_unavailable": "Chunk preview is unavailable.",
        "ingestion_tokens": "tokens",
        "ingestion_load_more_chunks": "Load more chunks",
        "ingestion_delete_document_aria": "Delete {name}",
        "ingestion_delete_document_title": "Delete document?",
        "ingestion_delete_document_message": "This removes the indexed chunks for {name}.",
        "ingestion_batch_limit": "Choose at most {count} files per batch.",
        "ingestion_clear_all": "Clear all",
        "ingestion_clear_all_title": "Clear every document?",
        "ingestion_clear_all_message": "This removes every indexed document and cannot be undone.",
        "ingestion_upload_progress": "Upload progress",
        "ingestion_upload_file_progress": "{name} progress",
        "ingestion_uploading": "Uploading…",
        "ingestion_waiting_progress": "Waiting for the next progress update…",
        "ingestion_progress_unavailable": "Upload progress is temporarily unavailable.",
        "ingestion_loading_documents": "Loading documents…",
        "ingestion_load_more_documents": "Load more documents",
        "ingestion_status_cancelled": "Cancelled",
        "ingestion_status_unchanged": "Unchanged",
        "ingestion_status_failed": "Failed",
        "ingestion_succeeded": "Succeeded",
        "ingestion_skipped": "Skipped",
        "ingestion_failed": "Failed",
        "ingestion_unit_bytes": "B",
        "ingestion_unit_kilobytes": "KB",
        "ingestion_unit_megabytes": "MB",
        "ingestion_upload_failed": "Ingestion failed.",
    }
    expected_ru = {
        "nav_dashboard": "Панель",
        "nav_coming_soon": "Скоро",
        "settings_workspace_eyebrow": "Рабочее пространство конфигурации",
        "settings_local_encrypted_status": "Локальные зашифрованные настройки",
        "settings_provider_list_unavailable": "Список провайдеров недоступен; показаны безопасные значения по умолчанию.",
        "settings_generation": "Генерация",
        "settings_answer_behavior": "Поведение ответа",
        "settings_index_behavior": "Поведение индекса",
        "settings_knowledge_index": "База знаний",
        "settings_observability": "Наблюдаемость",
        "settings_model_connection": "Подключение модели",
        "settings_provider_coming_soon": "скоро будет доступно",
        "settings_stored_keys_helper": "Сохранённые ключи скрыты. Вводите значение только при замене ключа.",
        "settings_all_changes_saved": "Все изменения сохранены",
        "settings_unsaved_changes": "Есть несохранённые изменения",
        "settings_upload_file_types_helper": "TXT, MD, PDF, DOCX или CSV · до 50 МБ каждый · {count} файлов в пакете",
        "settings_unavailable": "Настройки временно недоступны. Повторите попытку.",
        "settings_loading": "Загрузка настроек",
        "settings_discard_changes": "Отменить изменения",
        "settings_cached_model_list": "Список моделей из кэша",
        "ingestion_file_type_unknown": "Файл",
        "ingestion_hide_chunks": "Скрыть",
        "ingestion_loading_chunks": "Загрузка фрагментов…",
        "ingestion_chunk_preview_unavailable": "Предпросмотр фрагмента недоступен.",
        "ingestion_tokens": "токенов",
        "ingestion_load_more_chunks": "Загрузить ещё фрагменты",
        "ingestion_delete_document_aria": "Удалить {name}",
        "ingestion_delete_document_title": "Удалить документ?",
        "ingestion_delete_document_message": "Будут удалены проиндексированные фрагменты файла {name}.",
        "ingestion_batch_limit": "Выберите не более {count} файлов за один пакет.",
        "ingestion_clear_all": "Очистить всё",
        "ingestion_clear_all_title": "Очистить все документы?",
        "ingestion_clear_all_message": "Будут удалены все проиндексированные документы без возможности восстановления.",
        "ingestion_upload_progress": "Ход загрузки",
        "ingestion_upload_file_progress": "Ход загрузки {name}",
        "ingestion_uploading": "Загрузка…",
        "ingestion_waiting_progress": "Ожидание следующего обновления хода загрузки…",
        "ingestion_progress_unavailable": "Ход загрузки временно недоступен.",
        "ingestion_loading_documents": "Загрузка документов…",
        "ingestion_load_more_documents": "Загрузить ещё документы",
        "ingestion_status_cancelled": "Отменено",
        "ingestion_status_unchanged": "Без изменений",
        "ingestion_status_failed": "Не удалось",
        "ingestion_succeeded": "Успешно",
        "ingestion_skipped": "Пропущено",
        "ingestion_failed": "Не удалось",
        "ingestion_unit_bytes": "Б",
        "ingestion_unit_kilobytes": "КБ",
        "ingestion_unit_megabytes": "МБ",
        "ingestion_upload_failed": "Не удалось загрузить документ.",
    }

    assert {key: en[key] for key in expected_en} == expected_en
    assert {key: ru[key] for key in expected_ru} == expected_ru


def test_settings_and_ingestion_visible_copy_uses_authoritative_translation_keys() -> (
    None
):
    settings_source = _production_component_source(FEATURE_COMPONENT_ROOTS[0])
    settings_form = SETTINGS_FORM_PATH.read_text(encoding="utf-8")
    ingestion_panel = INGESTION_PANEL_PATH.read_text(encoding="utf-8")

    assert 't("settings_unavailable")' in settings_source
    assert 't("settings_loading")' in settings_source
    assert 't("settings_discard_changes")' in settings_source
    assert 't("settings_cached_model_list")' in settings_form
    assert 't("settings_api_key_placeholder")' in settings_form
    assert 't("settings_api_key_ollama_placeholder")' in settings_form
    assert 't("settings_cancel")' in ingestion_panel
    assert (
        "Settings are temporarily unavailable. Please try again." not in settings_source
    )
    assert "Loading settings" not in settings_source
    assert "Discard changes" not in settings_source
    assert 'locale === "ru"' not in settings_source
    assert "Cached model list" not in settings_form
    assert "Not required for local models" not in settings_form
    assert '"sk-..."' not in settings_form
    assert ">Cancel<" not in ingestion_panel


def test_every_settings_and_ingestion_component_rejects_raw_visible_copy() -> None:
    source = "\n".join(map(_production_component_source, FEATURE_COMPONENT_ROOTS))

    raw_text = re.findall(r">([A-Za-z][^<>{\r\n]*)<", source)
    raw_accessibility = re.findall(
        r"(?:aria-label|placeholder|label)=\{?[\"`]([^\"`]+)", source
    )
    raw_user_message = re.findall(r"setBatchWarning\([\"`]([^\"`]+)", source)

    assert raw_text == []
    assert raw_accessibility == []
    assert raw_user_message == []
    assert 'locale === "ru"' not in source
    assert all(expression in source for expression in RUNTIME_DATA_EXPRESSIONS)


def test_react_locale_inventory_covers_every_authoritative_backend_key() -> None:
    assert REACT_INVENTORY_PATH.is_file(), (
        "Stage 2 requires the generated React locale inventory JSON"
    )

    inventory = json.loads(REACT_INVENTORY_PATH.read_text(encoding="utf-8"))
    assert inventory == {
        "en": sorted(_backend_locale("en")),
        "ru": sorted(_backend_locale("ru")),
    }


def test_react_locale_inventory_consumption_contract_runs_in_vitest() -> None:
    assert REACT_INVENTORY_CONTRACT_TEST_PATH.is_file(), (
        "Stage 2 requires an executable React locale inventory contract test"
    )
    assert PACKAGE_PATH.is_file(), "Stage 2 requires the frontend test runner"

    result = subprocess.run(
        [
            NPM_COMMAND,
            "run",
            "test",
            "--",
            "src/i18n/locale-inventory.contract.test.ts",
        ],
        cwd=FRONTEND_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
