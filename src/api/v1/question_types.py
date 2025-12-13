"""
API endpoints pour QuestionType

Gestion des types de questions (référentiel).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from src.database import get_db
from src.models import QuestionType
from src.schemas.question_type import (
    QuestionTypeResponse,
    QuestionTypeListResponse,
    QuestionTypeCreate,
    QuestionTypeUpdate,
    QuestionTypePublic
)

router = APIRouter(prefix="/question-types", tags=["question-types"])


@router.get("", response_model=QuestionTypeListResponse, status_code=status.HTTP_200_OK)
async def list_question_types(
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """
    Liste tous les types de questions disponibles.

    Args:
        active_only: Si True, retourne uniquement les types actifs (défaut: True)
        db: Session de base de données

    Returns:
        Liste des types de questions avec leur nombre total
    """
    query = db.query(QuestionType)

    if active_only:
        query = query.filter_by(is_active=True)

    types = query.order_by(QuestionType.display_order).all()

    return {
        "question_types": types,
        "total": len(types)
    }


@router.get("/public", response_model=List[QuestionTypePublic], status_code=status.HTTP_200_OK)
async def list_question_types_public(db: Session = Depends(get_db)):
    """
    Liste publique simplifiée des types de questions actifs.

    Utilisée par le frontend pour afficher les options de types
    dans les formulaires de création de questions.

    Returns:
        Liste simplifiée des types actifs (code, label, icon, has_options)
    """
    types = db.query(QuestionType).filter_by(
        is_active=True
    ).order_by(
        QuestionType.display_order
    ).all()

    return types


@router.get("/{code}", response_model=QuestionTypeResponse, status_code=status.HTTP_200_OK)
async def get_question_type(
    code: str,
    db: Session = Depends(get_db)
):
    """
    Récupère un type de question par son code.

    Args:
        code: Code du type (ex: "boolean", "single_choice")
        db: Session de base de données

    Returns:
        Détails complets du type de question

    Raises:
        HTTPException 404: Si le type n'existe pas
    """
    question_type = db.query(QuestionType).filter_by(code=code).first()

    if not question_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Type de question '{code}' non trouvé"
        )

    return question_type


@router.post("", response_model=QuestionTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_question_type(
    question_type_data: QuestionTypeCreate,
    db: Session = Depends(get_db)
):
    """
    Crée un nouveau type de question.

    Args:
        question_type_data: Données du nouveau type
        db: Session de base de données

    Returns:
        Type de question créé

    Raises:
        HTTPException 400: Si le code existe déjà
    """
    # Vérifier si le code existe déjà
    existing = db.query(QuestionType).filter_by(code=question_type_data.code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Un type avec le code '{question_type_data.code}' existe déjà"
        )

    # Créer le nouveau type
    new_type = QuestionType(**question_type_data.model_dump())
    db.add(new_type)
    db.commit()
    db.refresh(new_type)

    return new_type


@router.patch("/{code}", response_model=QuestionTypeResponse, status_code=status.HTTP_200_OK)
async def update_question_type(
    code: str,
    question_type_data: QuestionTypeUpdate,
    db: Session = Depends(get_db)
):
    """
    Met à jour un type de question existant.

    Args:
        code: Code du type à modifier
        question_type_data: Données à mettre à jour
        db: Session de base de données

    Returns:
        Type de question mis à jour

    Raises:
        HTTPException 404: Si le type n'existe pas
    """
    question_type = db.query(QuestionType).filter_by(code=code).first()

    if not question_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Type de question '{code}' non trouvé"
        )

    # Appliquer les mises à jour
    update_data = question_type_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(question_type, field, value)

    db.commit()
    db.refresh(question_type)

    return question_type


@router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question_type(
    code: str,
    force: bool = False,
    db: Session = Depends(get_db)
):
    """
    Désactive (ou supprime) un type de question.

    Par défaut, le type est désactivé (is_active=False) plutôt que supprimé
    pour préserver l'intégrité des données.

    Args:
        code: Code du type à supprimer
        force: Si True, supprime réellement le type (dangereux!)
        db: Session de base de données

    Raises:
        HTTPException 404: Si le type n'existe pas
        HTTPException 409: Si le type est utilisé et force=False
    """
    question_type = db.query(QuestionType).filter_by(code=code).first()

    if not question_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Type de question '{code}' non trouvé"
        )

    if force:
        # Suppression réelle (peut échouer si FK utilisée)
        try:
            db.delete(question_type)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Impossible de supprimer: le type est utilisé par des questions existantes. Erreur: {str(e)}"
            )
    else:
        # Désactivation (soft delete)
        question_type.is_active = False
        db.commit()

    return None


@router.post("/{code}/activate", response_model=QuestionTypeResponse, status_code=status.HTTP_200_OK)
async def activate_question_type(
    code: str,
    db: Session = Depends(get_db)
):
    """
    Réactive un type de question désactivé.

    Args:
        code: Code du type à réactiver
        db: Session de base de données

    Returns:
        Type de question réactivé

    Raises:
        HTTPException 404: Si le type n'existe pas
    """
    question_type = db.query(QuestionType).filter_by(code=code).first()

    if not question_type:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Type de question '{code}' non trouvé"
        )

    question_type.is_active = True
    db.commit()
    db.refresh(question_type)

    return question_type
