from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base

ModelT = TypeVar("ModelT", bound=Base)


def list_items(db: Session, model: type[ModelT], skip: int = 0, limit: int = 50) -> list[ModelT]:
    return list(db.scalars(select(model).offset(skip).limit(limit)))


def get_item(db: Session, model: type[ModelT], item_id: int) -> ModelT | None:
    return db.get(model, item_id)


def create_item(db: Session, model: type[ModelT], data: dict[str, Any]) -> ModelT:
    item = model(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(db: Session, item: ModelT, data: dict[str, Any]) -> ModelT:
    for key, value in data.items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item
