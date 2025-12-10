"""Endpoints de test pour la vue audité (temporaire - Phase 1 MVP)"""
from typing import List
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import json

from src.database import get_db
from src.models.audit import Questionnaire, Question
from src.schemas.audite import (
    QuestionnaireForAuditeResponse,
    QuestionForAuditeResponse,
    DomainNode,
)
from src.services.question_option_service import QuestionOptionService

router = APIRouter()


@router.get("/test/{questionnaire_id}", response_model=QuestionnaireForAuditeResponse)
async def get_test_questionnaire(
    questionnaire_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Endpoint de TEST pour valider l'interface audité sans campagne
    Génère un audit_id de test et retourne le questionnaire
    """
    # Récupérer le questionnaire
    questionnaire = db.query(Questionnaire).filter(
        Questionnaire.id == questionnaire_id
    ).first()

    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire non trouvé")

    # Récupérer toutes les questions
    questions = db.query(Question).filter(
        Question.questionnaire_id == questionnaire_id,
        Question.is_active == True
    ).order_by(Question.sort_order).all()

    if not questions:
        raise HTTPException(
            status_code=404,
            detail="Aucune question trouvée pour ce questionnaire"
        )

    # Construire l'arbre des domaines (grouper par requirement_id)
    domain_tree, questions_by_node = _build_test_domain_tree(questions, db)

    # Calculer les statistiques (aucune réponse pour le test)
    total_questions = len(questions)
    answered_questions = 0
    mandatory_questions = len([q for q in questions if q.is_required])
    mandatory_answered = 0

    progress_percentage = 0
    can_submit = mandatory_questions == 0  # Peut soumettre seulement si pas de mandatory

    # Générer un audit_id de test (UUID v4)
    test_audit_id = uuid4()

    return QuestionnaireForAuditeResponse(
        id=questionnaire.id,
        name=questionnaire.name,
        audit_id=test_audit_id,  # ✅ Ajout du audit_id de test
        campaign_id=None,  # Pas de campagne pour le test
        domain_tree=domain_tree,
        questions_by_node=questions_by_node,
        total_questions=total_questions,
        answered_questions=answered_questions,
        mandatory_questions=mandatory_questions,
        mandatory_answered=mandatory_answered,
        progress_percentage=progress_percentage,
        can_submit=can_submit
    )


def _build_test_domain_tree(
    questions: List[Question],
    db: Session
) -> tuple[List[DomainNode], dict]:
    """
    Construit l'arbre hiérarchique des domaines pour le test (sans réponses)
    Utilise la vraie structure du référentiel avec parent/enfant
    """
    from sqlalchemy import text
    from src.schemas.audite import QuestionOption

    # 1. Récupérer le framework_id depuis les questions
    framework_id = None
    for q in questions:
        if q.framework_id:
            framework_id = q.framework_id
            break

    if not framework_id:
        # Fallback: arbre simple plat si pas de framework
        return _build_fallback_flat_tree(questions, db)

    # 2. Récupérer TOUS les domaines du framework avec leur hiérarchie
    domains_query = text("""
        WITH RECURSIVE domain_hierarchy AS (
            -- Domaines racines (level 0)
            SELECT
                d.id,
                d.parent_id,
                d.code,
                COALESCE(dt.title, d.code_officiel, d.code) as title,
                d.level,
                d.sort_index,
                ARRAY[d.id] as path
            FROM domain d
            LEFT JOIN domain_title dt ON dt.domain_id = d.id
                AND dt.language = 'fr'
                AND dt.is_primary = true
            WHERE d.framework_id = :framework_id
                AND (d.parent_id IS NULL OR d.level = 0)

            UNION ALL

            -- Sous-domaines récursifs
            SELECT
                d.id,
                d.parent_id,
                d.code,
                COALESCE(dt.title, d.code_officiel, d.code) as title,
                d.level,
                d.sort_index,
                dh.path || d.id
            FROM domain d
            JOIN domain_hierarchy dh ON d.parent_id = dh.id
            LEFT JOIN domain_title dt ON dt.domain_id = d.id
                AND dt.language = 'fr'
                AND dt.is_primary = true
        )
        SELECT * FROM domain_hierarchy
        ORDER BY path, sort_index NULLS LAST, code
    """)

    domain_rows = db.execute(domains_query, {"framework_id": str(framework_id)}).fetchall()

    # 3. Grouper les questions par domain_id (via requirement)
    questions_by_domain_id = {}
    for question in questions:
        if question.requirement_id:
            # Récupérer le domain_id depuis requirement
            req_domain = db.execute(
                text("SELECT domain_id FROM requirement WHERE id = :req_id"),
                {"req_id": str(question.requirement_id)}
            ).first()

            if req_domain and req_domain.domain_id:
                domain_id = str(req_domain.domain_id)
                if domain_id not in questions_by_domain_id:
                    questions_by_domain_id[domain_id] = []
                questions_by_domain_id[domain_id].append(question)

    # 4. Construire l'arbre hiérarchique
    domain_map = {}  # domain_id -> DomainNode
    questions_by_node = {}  # domain_id -> List[QuestionForAuditeResponse]

    for row in domain_rows:
        domain_id = str(row.id)
        domain_questions = questions_by_domain_id.get(domain_id, [])

        # Convertir les questions de ce domaine
        if domain_questions:
            questions_by_node[domain_id] = []
            for q in domain_questions:
                options_list = QuestionOptionService.get_options_as_list(db, q.id)
                options_formatted = None
                if options_list:
                    options_formatted = [
                        QuestionOption(label=opt, value=opt)
                        for opt in options_list
                    ]

                questions_by_node[domain_id].append(
                    QuestionForAuditeResponse(
                        id=q.id,
                        question_text=q.question_text,
                        response_type=q.response_type,
                        is_required=q.is_required,
                        help_text=q.help_text,
                        options=options_formatted,
                        upload_conditions=json.loads(q.upload_conditions) if isinstance(q.upload_conditions, str) and q.upload_conditions else (q.upload_conditions if isinstance(q.upload_conditions, dict) else None),
                        order_index=q.sort_order,
                        current_answer=None
                    )
                )

        # Créer le nœud de domaine
        has_questions = len(domain_questions) > 0
        has_mandatory = any(q.is_required for q in domain_questions)

        node = DomainNode(
            id=domain_id,
            name=f"{row.code} - {row.title}" if row.code else row.title,
            type="domain",
            order_index=row.sort_index if row.sort_index is not None else 999,
            children=[],  # Sera rempli après
            question_count=len(domain_questions),
            answered_count=0,
            has_mandatory_unanswered=has_mandatory
        )

        domain_map[domain_id] = node

    # 5. Reconstruire la hiérarchie parent/enfant
    root_nodes = []
    for row in domain_rows:
        domain_id = str(row.id)
        node = domain_map.get(domain_id)
        if not node:
            continue

        if row.parent_id is None or row.level == 0:
            root_nodes.append(node)
        else:
            parent_id = str(row.parent_id)
            parent_node = domain_map.get(parent_id)
            if parent_node:
                parent_node.children.append(node)

    # 6. Ne garder que les branches avec des questions (élagage)
    def has_questions_in_subtree(node: DomainNode) -> bool:
        """Vérifie si ce nœud ou ses descendants ont des questions"""
        if node.question_count > 0:
            return True
        return any(has_questions_in_subtree(child) for child in node.children)

    def prune_tree(nodes: List[DomainNode]) -> List[DomainNode]:
        """Supprime les branches sans questions"""
        result = []
        for node in nodes:
            node.children = prune_tree(node.children)
            if has_questions_in_subtree(node):
                result.append(node)
        return result

    pruned_tree = prune_tree(root_nodes)

    return pruned_tree, questions_by_node


def _build_fallback_flat_tree(
    questions: List[Question],
    db: Session
) -> tuple[List[DomainNode], dict]:
    """
    Arbre de secours plat si pas de framework (regroupement simple)
    """
    from sqlalchemy import text
    from src.schemas.audite import QuestionOption

    questions_by_node = {"unclassified": []}

    for q in questions:
        options_list = QuestionOptionService.get_options_as_list(db, q.id)
        options_formatted = None
        if options_list:
            options_formatted = [
                QuestionOption(label=opt, value=opt)
                for opt in options_list
            ]

        questions_by_node["unclassified"].append(
            QuestionForAuditeResponse(
                id=q.id,
                question_text=q.question_text,
                response_type=q.response_type,
                is_required=q.is_required,
                help_text=q.help_text,
                options=options_formatted,
                upload_conditions=json.loads(q.upload_conditions) if isinstance(q.upload_conditions, str) and q.upload_conditions else (q.upload_conditions if isinstance(q.upload_conditions, dict) else None),
                order_index=q.sort_order,
                current_answer=None
            )
        )

    node = DomainNode(
        id="unclassified",
        name="Questions non classées",
        type="domain",
        order_index=0,
        children=[],
        question_count=len(questions),
        answered_count=0,
        has_mandatory_unanswered=any(q.is_required for q in questions)
    )

    return [node], questions_by_node


@router.get("/list-questionnaires")
async def list_questionnaires_for_test(db: Session = Depends(get_db)):
    """
    Liste tous les questionnaires disponibles pour test
    Accepte tous les statuts (draft, published) pour faciliter les tests
    """
    questionnaires = db.query(Questionnaire).all()

    return {
        "questionnaires": [
            {
                "id": str(q.id),
                "name": q.name,
                "test_url": f"/audite/test-audit-id/{q.id}",
                "question_count": db.query(func.count(Question.id)).filter(
                    Question.questionnaire_id == q.id,
                    Question.is_active == True
                ).scalar()
            }
            for q in questionnaires
        ]
    }
