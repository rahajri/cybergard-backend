"""
backend/src/api/v1/category_relationships.py
Routes pour la gestion des relations many-to-many entre catégories
Permet à une catégorie d'avoir plusieurs parents (ex: MAROC sous FOURNISSEURS et CLIENTS)
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text, select
import uuid
import logging

from src.database import get_db
from src.models.category_relationship import CategoryRelationship
from src.models.category import Category
from src.models.audit import User
from src.dependencies_keycloak import get_current_user_keycloak, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Relations de Catégories"])


# ============================================================================
# SCHEMAS PYDANTIC
# ============================================================================

from pydantic import BaseModel
from datetime import datetime

class CategoryRelationshipCreate(BaseModel):
    """Schema pour créer une nouvelle relation parent-enfant"""
    parent_category_id: str
    child_category_id: str
    is_primary: bool = False

class CategoryRelationshipResponse(BaseModel):
    """Schema de réponse pour une relation"""
    id: str
    parent_category_id: str
    child_category_id: str
    parent_category_name: str
    child_category_name: str
    is_primary: bool
    created_at: datetime

class CategoryWithParentsResponse(BaseModel):
    """Schema pour une catégorie avec tous ses parents"""
    id: str
    name: str
    entity_category: str
    parents: List[dict]  # Liste des parents avec leurs infos


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/categories/{category_id}/parents", response_model=List[dict])
async def get_category_parents(
    category_id: str,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère tous les parents d'une catégorie

    Exemple:
    - MAROC (id: uuid-3) a les parents:
      - FOURNISSEURS (id: uuid-1) [PRIMAIRE]
      - CLIENTS (id: uuid-2)
    """
    try:
        query = """
            SELECT
                cr.id as relationship_id,
                cr.parent_category_id,
                cr.is_primary,
                cr.created_at,
                c.name as parent_name,
                c.entity_category as parent_entity_category
            FROM category_relationships cr
            INNER JOIN categories c ON cr.parent_category_id = c.id
            WHERE cr.child_category_id = :category_id
            AND c.is_active = true
            ORDER BY cr.is_primary DESC, c.name
        """

        result = db.execute(
            sql_text(query),
            {"category_id": category_id}
        ).fetchall()

        logger.info(f"📋 {len(result)} parents trouvés pour catégorie {category_id}")

        return [
            {
                "relationship_id": str(row[0]),
                "parent_category_id": str(row[1]),
                "is_primary": row[2],
                "created_at": row[3],
                "parent_name": row[4],
                "parent_entity_category": row[5]
            }
            for row in result
        ]

    except Exception as e:
        logger.error(f"❌ Erreur récupération parents: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des parents: {str(e)}"
        )


@router.get("/categories/{category_id}/contexts", response_model=dict)
async def get_category_contexts(
    category_id: str,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Récupère tous les contextes hiérarchiques d'une catégorie

    Retourne les chemins complets pour chaque parent

    Exemple pour MAROC:
    {
        "category_id": "uuid-3",
        "category_name": "MAROC",
        "contexts": [
            {
                "path": "FOURNISSEURS → MAROC",
                "parent_id": "uuid-1",
                "parent_name": "FOURNISSEURS",
                "is_primary": true
            },
            {
                "path": "CLIENTS → MAROC",
                "parent_id": "uuid-2",
                "parent_name": "CLIENTS",
                "is_primary": false
            }
        ]
    }
    """
    try:
        # Récupérer la catégorie
        category_query = """
            SELECT id, name, entity_category
            FROM categories
            WHERE id = :category_id AND is_active = true
        """

        category = db.execute(
            sql_text(category_query),
            {"category_id": category_id}
        ).fetchone()

        if not category:
            raise HTTPException(
                status_code=404,
                detail=f"Catégorie {category_id} introuvable"
            )

        # Récupérer tous les parents
        parents_query = """
            SELECT
                cr.parent_category_id,
                c.name as parent_name,
                cr.is_primary
            FROM category_relationships cr
            INNER JOIN categories c ON cr.parent_category_id = c.id
            WHERE cr.child_category_id = :category_id
            AND c.is_active = true
            ORDER BY cr.is_primary DESC, c.name
        """

        parents = db.execute(
            sql_text(parents_query),
            {"category_id": category_id}
        ).fetchall()

        contexts = []
        for parent in parents:
            path = f"{parent[1]} → {category[1]}"
            contexts.append({
                "path": path,
                "parent_id": str(parent[0]),
                "parent_name": parent[1],
                "is_primary": parent[2]
            })

        return {
            "category_id": str(category[0]),
            "category_name": category[1],
            "entity_category": category[2],
            "contexts": contexts
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur récupération contextes: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des contextes: {str(e)}"
        )


@router.post("/categories/relationships", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_category_relationship(
    relationship_data: CategoryRelationshipCreate,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Créer une nouvelle relation parent-enfant entre deux catégories

    Permet de créer des relations many-to-many

    Exemple:
    - Ajouter MAROC sous CLIENTS (en plus de FOURNISSEURS)

    Body:
    {
        "parent_category_id": "uuid-2",  // CLIENTS
        "child_category_id": "uuid-3",   // MAROC
        "is_primary": false
    }
    """
    try:
        parent_id = relationship_data.parent_category_id
        child_id = relationship_data.child_category_id

        # ========================================================================
        # 1. Vérifier que les deux catégories existent
        # ========================================================================
        parent = db.execute(
            select(Category).where(Category.id == uuid.UUID(parent_id))
        ).scalar_one_or_none()

        child = db.execute(
            select(Category).where(Category.id == uuid.UUID(child_id))
        ).scalar_one_or_none()

        if not parent:
            raise HTTPException(
                status_code=404,
                detail=f"Catégorie parente {parent_id} introuvable"
            )

        if not child:
            raise HTTPException(
                status_code=404,
                detail=f"Catégorie enfant {child_id} introuvable"
            )

        # ========================================================================
        # 2. Vérifier qu'on ne crée pas une boucle (parent ne peut pas être enfant)
        # ========================================================================
        if parent_id == child_id:
            raise HTTPException(
                status_code=400,
                detail="Une catégorie ne peut pas être son propre parent"
            )

        # ========================================================================
        # 3. Vérifier que la relation n'existe pas déjà
        # ========================================================================
        existing_query = """
            SELECT id FROM category_relationships
            WHERE parent_category_id = :parent_id
            AND child_category_id = :child_id
        """

        existing = db.execute(
            sql_text(existing_query),
            {"parent_id": parent_id, "child_id": child_id}
        ).fetchone()

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Une relation existe déjà entre {parent.name} et {child.name}"
            )

        # ========================================================================
        # 4. Si is_primary=true, retirer le flag primary des autres relations
        # ========================================================================
        if relationship_data.is_primary:
            update_query = """
                UPDATE category_relationships
                SET is_primary = false
                WHERE child_category_id = :child_id
            """
            db.execute(sql_text(update_query), {"child_id": child_id})

        # ========================================================================
        # 5. Créer la nouvelle relation
        # ========================================================================
        new_relationship = CategoryRelationship(
            id=uuid.uuid4(),
            parent_category_id=uuid.UUID(parent_id),
            child_category_id=uuid.UUID(child_id),
            is_primary=relationship_data.is_primary,
            created_by=current_user.email if hasattr(current_user, 'email') else None
        )

        db.add(new_relationship)
        db.commit()
        db.refresh(new_relationship)

        logger.info(f"✅ Relation créée: {parent.name} → {child.name} (primary={relationship_data.is_primary})")

        # ========================================================================
        # 6. Mettre à jour parent_category_id si c'est la relation primaire
        # ========================================================================
        if relationship_data.is_primary:
            child.parent_category_id = uuid.UUID(parent_id)
            db.commit()
            logger.info(f"✅ parent_category_id mis à jour: {child.name}.parent_category_id = {parent_id}")

        return {
            "id": str(new_relationship.id),
            "parent_category_id": str(new_relationship.parent_category_id),
            "child_category_id": str(new_relationship.child_category_id),
            "parent_name": parent.name,
            "child_name": child.name,
            "is_primary": new_relationship.is_primary,
            "created_at": new_relationship.created_at,
            "message": f"Relation créée: {parent.name} → {child.name}"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur création relation: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création de la relation: {str(e)}"
        )


@router.delete("/categories/relationships/{relationship_id}", status_code=status.HTTP_200_OK)
async def delete_category_relationship(
    relationship_id: str,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Supprimer une relation parent-enfant

    IMPORTANT: Si c'est la relation primaire, il faut d'abord promouvoir une autre relation

    Retourne les entités affectées pour migration manuelle
    """
    try:
        # ========================================================================
        # 1. Vérifier que la relation existe
        # ========================================================================
        relationship = db.execute(
            select(CategoryRelationship).where(
                CategoryRelationship.id == uuid.UUID(relationship_id)
            )
        ).scalar_one_or_none()

        if not relationship:
            raise HTTPException(
                status_code=404,
                detail=f"Relation {relationship_id} introuvable"
            )

        # ========================================================================
        # 2. Vérifier si c'est la relation primaire
        # ========================================================================
        if relationship.is_primary:
            # Compter combien d'autres relations existent pour cet enfant
            count_query = """
                SELECT COUNT(*) FROM category_relationships
                WHERE child_category_id = :child_id
                AND id != :relationship_id
            """

            other_count = db.execute(
                sql_text(count_query),
                {
                    "child_id": str(relationship.child_category_id),
                    "relationship_id": relationship_id
                }
            ).scalar()

            if other_count == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Impossible de supprimer la dernière relation. Créez d'abord une autre relation ou supprimez la catégorie."
                )

            # Promouvoir automatiquement la première autre relation
            promote_query = """
                UPDATE category_relationships
                SET is_primary = true
                WHERE child_category_id = :child_id
                AND id != :relationship_id
                LIMIT 1
            """

            db.execute(
                sql_text(promote_query),
                {
                    "child_id": str(relationship.child_category_id),
                    "relationship_id": relationship_id
                }
            )

            logger.info(f"⚠️ Relation primaire supprimée, une autre relation a été promue")

        # ========================================================================
        # 3. Compter les entités affectées (pour information)
        # ========================================================================
        entities_query = """
            SELECT COUNT(*) FROM ecosystem_entity
            WHERE category_id = :category_id
        """

        entities_count = db.execute(
            sql_text(entities_query),
            {"category_id": str(relationship.child_category_id)}
        ).scalar()

        # ========================================================================
        # 4. Supprimer la relation
        # ========================================================================
        parent_name = relationship.parent_category.name if relationship.parent_category else "?"
        child_name = relationship.child_category.name if relationship.child_category else "?"

        db.delete(relationship)
        db.commit()

        logger.info(f"✅ Relation supprimée: {parent_name} → {child_name}")

        return {
            "message": f"Relation supprimée: {parent_name} → {child_name}",
            "entities_affected": entities_count,
            "warning": f"{entities_count} entités sont toujours associées à cette catégorie" if entities_count > 0 else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur suppression relation: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression de la relation: {str(e)}"
        )


@router.patch("/categories/relationships/{relationship_id}/promote", status_code=status.HTTP_200_OK)
async def promote_relationship_to_primary(
    relationship_id: str,
    current_user: User = Depends(require_permission("REFERENTIAL_READ")),
    db: Session = Depends(get_db)
):
    """
    Promouvoir une relation en tant que relation primaire

    Cela va:
    1. Mettre is_primary=false sur toutes les autres relations de cet enfant
    2. Mettre is_primary=true sur cette relation
    3. Mettre à jour parent_category_id dans la table categories
    """
    try:
        # ========================================================================
        # 1. Vérifier que la relation existe
        # ========================================================================
        relationship = db.execute(
            select(CategoryRelationship).where(
                CategoryRelationship.id == uuid.UUID(relationship_id)
            )
        ).scalar_one_or_none()

        if not relationship:
            raise HTTPException(
                status_code=404,
                detail=f"Relation {relationship_id} introuvable"
            )

        if relationship.is_primary:
            return {
                "message": "Cette relation est déjà la relation primaire",
                "is_primary": True
            }

        # ========================================================================
        # 2. Retirer le flag primary de toutes les autres relations
        # ========================================================================
        update_query = """
            UPDATE category_relationships
            SET is_primary = false
            WHERE child_category_id = :child_id
        """

        db.execute(
            sql_text(update_query),
            {"child_id": str(relationship.child_category_id)}
        )

        # ========================================================================
        # 3. Promouvoir cette relation
        # ========================================================================
        relationship.is_primary = True

        # ========================================================================
        # 4. Mettre à jour parent_category_id dans categories
        # ========================================================================
        child_category = db.execute(
            select(Category).where(Category.id == relationship.child_category_id)
        ).scalar_one()

        child_category.parent_category_id = relationship.parent_category_id

        db.commit()

        parent_name = relationship.parent_category.name if relationship.parent_category else "?"
        child_name = relationship.child_category.name if relationship.child_category else "?"

        logger.info(f"✅ Relation promue en primaire: {parent_name} → {child_name}")

        return {
            "message": f"Relation promue: {parent_name} → {child_name} est maintenant la relation primaire",
            "relationship_id": str(relationship.id),
            "is_primary": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur promotion relation: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la promotion de la relation: {str(e)}"
        )
