"""Endpoints de prévisualisation de questionnaire pour les admins"""
from typing import List, Dict
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from src.database import get_db
from src.schemas.audite import (
    QuestionnaireForAuditeResponse,
    QuestionForAuditeResponse,
    QuestionOption,
    DomainNode,
)

router = APIRouter()


@router.get("/preview/{questionnaire_id}", response_model=QuestionnaireForAuditeResponse)
async def preview_questionnaire(
    questionnaire_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Prévisualisation d'un questionnaire côté admin
    Utilise des requêtes SQL directes pour éviter les dépendances ORM complexes
    Permet aux admins de voir le rendu du questionnaire tel qu'un audité le verrait
    """
    # Requête SQL directe pour le questionnaire
    q_result = db.execute(
        text("SELECT id, name, status FROM questionnaire WHERE id = :id"),
        {"id": str(questionnaire_id)}
    )
    q_row = q_result.fetchone()

    if not q_row:
        raise HTTPException(status_code=404, detail="Questionnaire non trouvé")

    # Récupérer toutes les questions
    questions_result = db.execute(
        text("""
            SELECT id, question_text, response_type, is_required, help_text,
                   validation_rules, upload_conditions, sort_order, requirement_id
            FROM question
            WHERE questionnaire_id = :id AND is_active = true
            ORDER BY COALESCE(sort_order, 0)
        """),
        {"id": str(questionnaire_id)}
    )
    questions = questions_result.fetchall()

    if not questions:
        raise HTTPException(
            status_code=404,
            detail="Aucune question trouvée pour ce questionnaire"
        )

    # Grouper les questions
    # Si les questions ont des requirement_id, grouper par requirement
    # Sinon, créer des groupes artificiels par tranche de 20 questions
    has_requirements = any(q.requirement_id for q in questions)

    questions_by_req = {}
    if has_requirements:
        # Grouper par requirement_id
        for q in questions:
            req_id = str(q.requirement_id) if q.requirement_id else "unclassified"
            if req_id not in questions_by_req:
                questions_by_req[req_id] = []
            questions_by_req[req_id].append(q)
    else:
        # Créer des groupes artificiels par tranche de 20 questions
        questions_per_group = 20
        for i in range(0, len(questions), questions_per_group):
            group_id = f"group_{i // questions_per_group + 1}"
            questions_by_req[group_id] = questions[i:i + questions_per_group]

    # Récupérer les noms des requirements
    # Filtrer uniquement les vrais requirement_ids (pas "unclassified" ni "group_X")
    req_ids_list = [
        r for r in questions_by_req.keys()
        if r != "unclassified" and not r.startswith("group_")
    ]
    req_names = {}
    if req_ids_list:
        # Construire la requête IN au lieu de ANY pour éviter les problèmes de cast
        placeholders = ", ".join([f":req_id_{i}" for i in range(len(req_ids_list))])
        params = {f"req_id_{i}": req_id for i, req_id in enumerate(req_ids_list)}

        req_result = db.execute(
            text(f"""
                SELECT id, official_code, chapter_path
                FROM requirement
                WHERE id IN ({placeholders})
            """),
            params
        )
        for row in req_result:
            # Utiliser chapter_path qui contient le nom complet
            name = row.chapter_path if row.chapter_path else f"Exigence {row.official_code}"
            req_names[str(row.id)] = name

    # Construire l'arbre
    domain_tree = []
    questions_by_node = {}

    for idx, (req_id, req_questions) in enumerate(sorted(questions_by_req.items())):
        has_mandatory = any(q.is_required for q in req_questions)

        # Récupérer le vrai nom du requirement
        if req_id == "unclassified":
            node_name = "Non classé"
        else:
            node_name = req_names.get(req_id, f"Domaine {idx + 1}")

        node = DomainNode(
            id=req_id,
            name=node_name,
            type="requirement",
            order_index=idx,
            children=[],
            question_count=len(req_questions),
            answered_count=0,
            has_mandatory_unanswered=has_mandatory
        )
        domain_tree.append(node)

        # Convertir les questions
        questions_by_node[req_id] = []
        for idx, q in enumerate(req_questions):
            # Extraire les options depuis validation_rules si présent
            options = None
            if q.validation_rules and isinstance(q.validation_rules, dict):
                raw_options = q.validation_rules.get('options')
                if raw_options:
                    # Normaliser les options : si ce sont des strings, les convertir en objets
                    options = []
                    for opt in raw_options:
                        if isinstance(opt, dict):
                            # Déjà au bon format, créer un QuestionOption
                            options.append(QuestionOption(**opt))
                        elif isinstance(opt, str):
                            # Convertir string en objet {label, value}
                            options.append(QuestionOption(
                                label=opt,
                                value=opt.lower().replace(" ", "_").replace(",", "")
                            ))
                        else:
                            # Format inconnu, tenter de le convertir
                            try:
                                options.append(QuestionOption(label=str(opt), value=str(opt)))
                            except:
                                pass  # Ignorer les options invalides

            questions_by_node[req_id].append(
                QuestionForAuditeResponse(
                    id=str(q.id),
                    question_text=q.question_text,
                    response_type=q.response_type,
                    is_required=q.is_required,
                    help_text=q.help_text,
                    options=options,
                    # ✅ Parser le JSON upload_conditions si c'est une chaîne
                    upload_conditions=json.loads(q.upload_conditions) if isinstance(q.upload_conditions, str) and q.upload_conditions else (q.upload_conditions if isinstance(q.upload_conditions, dict) else None),
                    order_index=q.sort_order if q.sort_order else idx,
                    current_answer=None
                )
            )

    # Statistiques
    total_questions = len(questions)
    mandatory_questions = len([q for q in questions if q.is_required])

    # Générer un audit_id fictif pour la preview
    preview_audit_id = uuid4()

    return QuestionnaireForAuditeResponse(
        id=str(q_row.id),
        name=q_row.name,
        audit_id=preview_audit_id,  # ID fictif pour la preview
        campaign_id=None,  # Pas de campagne en mode preview
        domain_tree=domain_tree,
        questions_by_node=questions_by_node,
        total_questions=total_questions,
        answered_questions=0,
        mandatory_questions=mandatory_questions,
        mandatory_answered=0,
        progress_percentage=0,
        can_submit=(mandatory_questions == 0)
    )
