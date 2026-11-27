"""Russian public errors; provider names and machine codes are kept intact."""

import re

RUSSIAN = re.compile(r"[а-яё]", re.IGNORECASE)
STATUS_MESSAGES = {
    400: "Проверьте данные запроса.",
    401: "Войдите в аккаунт.",
    403: "Недостаточно прав для этого действия.",
    404: "Запрошенные данные не найдены.",
    405: "Это действие недоступно.",
    409: "Данные изменились. Обновите страницу и повторите действие.",
    410: "Данные больше недоступны.",
    413: "Слишком большой объём данных. Уменьшите размер файла или запроса.",
    415: "Этот формат данных не поддерживается.",
    422: "Проверьте заполненные поля.",
    429: "Слишком много попыток. Попробуйте позже.",
    500: "Не удалось выполнить действие. Попробуйте позже.",
    502: "Не удалось получить данные внешнего сервиса. Попробуйте позже.",
    503: "Сервис временно недоступен. Попробуйте позже.",
    504: "Сервис не ответил вовремя. Попробуйте позже.",
}


def public_message(value: object, status: int) -> str:
    if isinstance(value, str) and RUSSIAN.search(value):
        return value
    return STATUS_MESSAGES.get(status, "Не удалось выполнить действие. Попробуйте ещё раз.")


def validation_message(kind: str) -> str:
    if kind == "missing":
        return "Заполните обязательное поле."
    if kind in {"string_too_short", "too_short"}:
        return "Значение слишком короткое."
    if kind in {"string_too_long", "too_long"}:
        return "Значение слишком длинное."
    if kind.startswith(("int_", "float_", "decimal_")):
        return "Введите корректное число."
    if kind.startswith(("date_", "datetime_")):
        return "Введите корректную дату."
    if kind.startswith("bool_"):
        return "Выберите один из вариантов."
    if kind == "extra_forbidden":
        return "Это поле не поддерживается."
    if kind == "json_invalid":
        return "Не удалось прочитать данные запроса."
    return "Проверьте значение поля."
