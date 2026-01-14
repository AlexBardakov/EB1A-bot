# app/core/drafter.py
from sqlalchemy.orm import Session
from app.storage.models import Case, EvidenceItem, EvidenceStatus
from app.llm.openai_client import OpenAIClient
from app.llm.base import LLMResult


def generate_criterion_draft(session: Session, case_id: int,
                             criterion_tag: str) -> str:
    """
    Генерирует черновик петиции для заданного критерия на основе фактов.
    """
    # 1. Загружаем данные кейса
    case = session.query(Case).filter(Case.id == case_id).one()
    memo = case.memo_json or {}

    role = memo.get("role", "Expert")
    field = memo.get("field", "Specialized Field")
    pillars = memo.get("pillars", [])
    pillars_str = "; ".join(pillars) if isinstance(pillars, list) else str(
        pillars)

    # 2. Загружаем факты по этому критерию
    # Берем только verified или draft, сортируем по силе
    items = (
        session.query(EvidenceItem)
        .filter(
            EvidenceItem.case_id == case_id,
            EvidenceItem.criterion_tags.contains([criterion_tag])
            # PGVector/JSONB проверка
        )
        .order_by(EvidenceItem.strength.desc())  # Сначала сильные факты
        .all()
    )

    if not items:
        return "❌ Нет фактов, привязанных к этому критерию. Сначала добавьте их и проставьте теги."

    # 3. Формируем контекст из фактов
    evidence_list_text = ""
    for item in items:
        status_mark = "" if item.status == EvidenceStatus.verified else "(Черновик)"
        evidence_list_text += (
            f"- Exhibit {item.exhibit_code}: {item.description} "
            f"[Сила доказательства: {item.strength}/5] {status_mark}\n"
        )

    # 4. Составляем Промпт (Инструкция Юристу)
    system_prompt = (
        "Ты — опытный иммиграционный юрист, специализирующийся на петициях EB-1A (Extraordinary Ability). "
        "Твоя задача — написать убедительный проект секции петиции для конкретного критерия."
    )

    user_prompt = (
        f"ИСХОДНЫЕ ДАННЫЕ КЕЙСА:\n"
        f"Заявитель: {role}\n"
        f"Область: {field}\n"
        f"Ключевые опоры (Pillars): {pillars_str}\n\n"
        f"ЦЕЛЕВОЙ КРИТЕРИЙ: {criterion_tag}\n\n"
        f"СПИСОК ДОКАЗАТЕЛЬСТВ (ЭКСПИТЫ):\n"
        f"{evidence_list_text}\n\n"
        f"ЗАДАЧА:\n"
        f"Напиши черновик аргументации для этого критерия на Русском языке.\n"
        f"Требования:\n"
        f"1. Стиль: формально-юридический, убедительный, но без лишней воды.\n"
        f"2. Структура: Начни с тезиса, что заявитель соответствует критерию. Затем последовательно опиши доказательства.\n"
        f"3. ОБЯЗАТЕЛЬНО ссылайся на номера доказательств (например, 'Как подтверждается Exhibit A-1...').\n"
        f"4. Используй 'Pillars' (опоры) чтобы связать факты с глобальной стратегией кейса.\n"
        f"5. Не выдумывай факты, которых нет в списке.\n"
        f"6. Если факт помечен как слабый (1-2/5), подай его аккуратно или используй как вспомогательный.\n"
    )

    # 5. Вызываем AI (используем GPT-4o через OpenAIClient)
    # Если хотите Gemini, замените на GeminiClient()
    llm = OpenAIClient()

    result: LLMResult = llm.generate(
        system=system_prompt,
        user=user_prompt,
        temperature=0.4,  # Чуть креативности для связности, но не галлюцинаций
        max_output_tokens=2000
    )

    return result.text