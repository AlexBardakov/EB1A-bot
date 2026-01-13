# app/core/ingest.py
import os
import uuid
from datetime import datetime
from typing import Optional

# Библиотеки для текста
import docx
from pypdf import PdfReader

from sqlalchemy.orm import Session
from app.storage.models import Document, DocumentVersion, DocumentStatus, ChatState

# Папка для сохранения файлов (локально)
UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def extract_text_from_file(file_path: str, mime_type: str) -> str:
    """Извлекает чистый текст из PDF или DOCX."""
    text = ""
    try:
        if "pdf" in mime_type or file_path.endswith(".pdf"):
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() + "\n"

        elif "word" in mime_type or "document" in mime_type or file_path.endswith(".docx"):
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"

        else:
            return "[Error: Unsupported file format for text extraction]"

    except Exception as e:
        return f"[Error extracting text: {e}]"

    return text.strip()


def save_document_upload(
        session: Session,
        chat_id: str,
        file_name: str,
        file_data: bytes,
        mime_type: str
) -> str:
    """
    1. Находит активный кейс.
    2. Сохраняет файл на диск.
    3. Парсит текст.
    4. Создает запись в БД.
    """
    # 1. Проверка кейса
    cs = session.query(ChatState).filter(ChatState.chat_id == chat_id).one_or_none()
    if not cs or not cs.active_case_id:
        return "⚠️ Сначала выберите кейс через `/case use ...`"

    # 2. Сохранение на диск
    # Генерируем уникальное имя, чтобы не перезатереть файлы с одинаковым названием
    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(file_data)

    # 3. Экстракция текста
    extracted_text = extract_text_from_file(file_path, mime_type)
    if not extracted_text:
        extracted_text = "[No text extracted or empty file]"

    # 4. Запись в БД
    # Проверяем, есть ли уже документ с таким названием в этом кейсе
    existing_doc = (
        session.query(Document)
        .filter(Document.case_id == cs.active_case_id, Document.title == file_name)
        .one_or_none()
    )

    if existing_doc:
        doc = existing_doc
        msg_prefix = f"🔄 Обновляю документ '{file_name}'..."
    else:
        doc = Document(
            case_id=cs.active_case_id,
            title=file_name,
            doc_type="unknown",  # Можно потом уточнить
            status=DocumentStatus.draft
        )
        session.add(doc)
        session.flush()  # чтобы получить doc.id
        msg_prefix = f"✅ Создан новый документ '{file_name}'."

    # Создаем новую версию
    version = DocumentVersion(
        document_id=doc.id,
        storage_url=file_path,
        text_extract=extracted_text,
        created_by=f"user_{chat_id}"
    )
    session.add(version)
    session.flush()

    # Обновляем ссылку на текущую версию
    doc.current_version_id = version.id
    doc.updated_at = datetime.utcnow()

    return (
        f"{msg_prefix}\n"
        f"Распознано символов: {len(extracted_text)}\n"
        f"Теперь можно отправить: `/review {file_name}`"
    )