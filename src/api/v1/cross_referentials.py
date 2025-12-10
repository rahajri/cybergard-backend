"""
API endpoints for Cross-Referential Analysis
Provides data for cross-referential coverage via requirement_control_point
Shows how control points are shared across different frameworks
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime

from src.database import get_db

# ✅ REDIS CACHE
from src.utils.redis_manager import cache_result

router = APIRouter()


@router.get("/overview")
@cache_result(ttl=1800, key_prefix="cross_ref_overview")  # ✅ Cache 30min
async def get_cross_ref_overview(db: Session = Depends(get_db)):
    """
    Vue d'ensemble des cross-référentiels
    Statistiques globales sur les PCs partagés entre frameworks
    """
    try:
        # Statistiques globales
        stats_query = text("""
            SELECT
                COUNT(DISTINCT cp.id) as total_pcs,
                COUNT(DISTINCT rcp.requirement_id) as total_requirements,
                COUNT(DISTINCT f.id) as total_frameworks,
                COUNT(*) as total_mappings
            FROM control_point cp
            JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
            JOIN requirement r ON r.id = rcp.requirement_id
            JOIN framework f ON f.id = r.framework_id
        """)

        stats_result = db.execute(stats_query).fetchone()

        # PCs cross-référentiels (partagés entre plusieurs frameworks)
        cross_ref_query = text("""
            SELECT COUNT(DISTINCT cp.id) as cross_ref_pcs
            FROM control_point cp
            JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
            JOIN requirement r ON r.id = rcp.requirement_id
            JOIN framework f ON f.id = r.framework_id
            GROUP BY cp.id
            HAVING COUNT(DISTINCT f.id) > 1
        """)

        cross_ref_result = db.execute(cross_ref_query).fetchall()
        cross_ref_count = len(cross_ref_result)

        # Taux de déduplication
        total_pcs = stats_result.total_pcs if stats_result else 0
        total_reqs = stats_result.total_requirements if stats_result else 0
        deduplication_rate = ((total_reqs - total_pcs) / total_reqs * 100) if total_reqs > 0 else 0
        cross_ref_percentage = (cross_ref_count / total_pcs * 100) if total_pcs > 0 else 0

        return {
            "total_pcs": total_pcs,
            "total_requirements": total_reqs,
            "total_frameworks": stats_result.total_frameworks if stats_result else 0,
            "total_mappings": stats_result.total_mappings if stats_result else 0,
            "cross_ref_pcs": cross_ref_count,
            "cross_ref_percentage": round(cross_ref_percentage, 2),
            "deduplication_rate": round(deduplication_rate, 2)
        }

    except Exception as e:
        print(f"Error in overview: {e}")
        return {
            "total_pcs": 0,
            "total_requirements": 0,
            "total_frameworks": 0,
            "total_mappings": 0,
            "cross_ref_pcs": 0,
            "cross_ref_percentage": 0,
            "deduplication_rate": 0
        }


@router.get("/coverage-matrix")
@cache_result(ttl=1800, key_prefix="cross_ref_coverage_matrix")  # ✅ Cache 30min
async def get_coverage_matrix(db: Session = Depends(get_db)):
    """
    Matrice de couverture entre frameworks
    Montre combien de PCs sont partagés entre chaque paire de frameworks
    """
    try:
        # Récupérer tous les frameworks actifs
        frameworks_query = text("""
            SELECT DISTINCT f.id, f.code, f.name
            FROM framework f
            JOIN requirement r ON r.framework_id = f.id
            JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
            WHERE f.is_active = true
            ORDER BY f.code
        """)

        frameworks_result = db.execute(frameworks_query)
        frameworks = [
            {"id": str(row.id), "code": row.code, "name": row.name}
            for row in frameworks_result.fetchall()
        ]

        # Construire la matrice
        matrix = []
        for source_fw in frameworks:
            row_data = {
                "framework_code": source_fw["code"],
                "framework_name": source_fw["name"],
                "coverages": {}
            }

            for target_fw in frameworks:
                if source_fw["code"] == target_fw["code"]:
                    row_data["coverages"][target_fw["code"]] = None  # Même framework
                else:
                    # Compter les PCs partagés entre les deux frameworks
                    shared_pcs_query = text("""
                        SELECT COUNT(DISTINCT cp.id) as shared_count
                        FROM control_point cp
                        WHERE EXISTS (
                            SELECT 1 FROM requirement_control_point rcp1
                            JOIN requirement r1 ON r1.id = rcp1.requirement_id
                            WHERE rcp1.control_point_id = cp.id
                            AND r1.framework_id = :source_id
                        )
                        AND EXISTS (
                            SELECT 1 FROM requirement_control_point rcp2
                            JOIN requirement r2 ON r2.id = rcp2.requirement_id
                            WHERE rcp2.control_point_id = cp.id
                            AND r2.framework_id = :target_id
                        )
                    """)

                    result = db.execute(
                        shared_pcs_query,
                        {"source_id": source_fw["id"], "target_id": target_fw["id"]}
                    ).fetchone()

                    shared_count = result.shared_count if result else 0

                    # Calculer le pourcentage par rapport aux PCs du framework cible
                    total_target_pcs_query = text("""
                        SELECT COUNT(DISTINCT cp.id) as total_count
                        FROM control_point cp
                        JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
                        JOIN requirement r ON r.id = rcp.requirement_id
                        WHERE r.framework_id = :target_id
                    """)

                    target_result = db.execute(
                        total_target_pcs_query,
                        {"target_id": target_fw["id"]}
                    ).fetchone()

                    total_target = target_result.total_count if target_result else 1
                    coverage_pct = (shared_count / total_target * 100) if total_target > 0 else 0

                    row_data["coverages"][target_fw["code"]] = {
                        "percentage": round(coverage_pct, 1),
                        "shared_pcs": shared_count,
                        "total_pcs": total_target
                    }

            matrix.append(row_data)

        return {
            "frameworks": [fw["code"] for fw in frameworks],
            "matrix": matrix
        }

    except Exception as e:
        print(f"Error in coverage_matrix: {e}")
        import traceback
        traceback.print_exc()
        return {"frameworks": [], "matrix": []}


@router.get("/shared-control-points")
@cache_result(ttl=1800, key_prefix="cross_ref_shared_pcs")  # ✅ Cache 30min
async def get_shared_control_points(
    source_framework_id: Optional[str] = None,
    target_framework_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Liste des PCs partagés entre frameworks avec détails des exigences
    """
    try:
        # Construire la requête selon les filtres
        where_conditions = ["1=1"]
        params = {}

        if source_framework_id and source_framework_id != 'all':
            where_conditions.append("f1.id = :source_fw_id")
            params["source_fw_id"] = source_framework_id

        if target_framework_id and target_framework_id != 'all':
            where_conditions.append("f2.id = :target_fw_id")
            params["target_fw_id"] = target_framework_id

        where_clause = " AND ".join(where_conditions)

        query = text(f"""
            SELECT
                cp.id as pc_id,
                cp.code as pc_code,
                cp.name as pc_name,
                cp.description as pc_description,
                cp.criticality_level,
                cp.estimated_effort_hours,
                COUNT(DISTINCT f1.id) as nb_frameworks,
                STRING_AGG(DISTINCT f1.code, ', ' ORDER BY f1.code) as frameworks,
                COUNT(DISTINCT rcp.requirement_id) as nb_requirements,
                JSONB_AGG(
                    DISTINCT JSONB_BUILD_OBJECT(
                        'framework_code', f1.code,
                        'framework_name', f1.name,
                        'requirement_code', r1.official_code,
                        'requirement_title', r1.title
                    ) ORDER BY JSONB_BUILD_OBJECT(
                        'framework_code', f1.code,
                        'framework_name', f1.name,
                        'requirement_code', r1.official_code,
                        'requirement_title', r1.title
                    )
                ) as requirements
            FROM control_point cp
            JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
            JOIN requirement r1 ON r1.id = rcp.requirement_id
            JOIN framework f1 ON f1.id = r1.framework_id
            LEFT JOIN requirement_control_point rcp2 ON rcp2.control_point_id = cp.id
            LEFT JOIN requirement r2 ON r2.id = rcp2.requirement_id AND r2.framework_id != f1.id
            LEFT JOIN framework f2 ON f2.id = r2.framework_id
            WHERE {where_clause}
            GROUP BY cp.id, cp.code, cp.name, cp.description, cp.criticality_level, cp.estimated_effort_hours
            HAVING COUNT(DISTINCT f1.id) > 1 OR :source_fw_id IS NOT NULL OR :target_fw_id IS NOT NULL
            ORDER BY COUNT(DISTINCT rcp.requirement_id) DESC
            LIMIT 100
        """)

        # Ajouter les paramètres manquants pour HAVING
        if 'source_fw_id' not in params:
            params['source_fw_id'] = None
        if 'target_fw_id' not in params:
            params['target_fw_id'] = None

        result = db.execute(query, params)
        rows = result.fetchall()

        shared_pcs = []
        for row in rows:
            shared_pcs.append({
                "id": str(row.pc_id),
                "code": row.pc_code,
                "name": row.pc_name,
                "description": row.pc_description,
                "criticality_level": row.criticality_level,
                "estimated_effort_hours": row.estimated_effort_hours,
                "nb_frameworks": row.nb_frameworks,
                "frameworks": row.frameworks,
                "nb_requirements": row.nb_requirements,
                "requirements": row.requirements
            })

        return {
            "shared_control_points": shared_pcs,
            "total": len(shared_pcs)
        }

    except Exception as e:
        print(f"Error in shared_control_points: {e}")
        import traceback
        traceback.print_exc()
        return {"shared_control_points": [], "total": 0}


@router.get("/statistics")
@cache_result(ttl=1800, key_prefix="cross_ref_statistics")  # ✅ Cache 30min
async def get_statistics(db: Session = Depends(get_db)):
    """
    Statistiques détaillées sur les cross-référentiels
    """
    try:
        # Distribution des PCs par nombre de frameworks
        distribution_query = text("""
            SELECT
                COUNT(DISTINCT f.id) as nb_frameworks,
                COUNT(*) as nb_pcs
            FROM control_point cp
            JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
            JOIN requirement r ON r.id = rcp.requirement_id
            JOIN framework f ON f.id = r.framework_id
            GROUP BY cp.id
        """)

        distribution_result = db.execute(distribution_query).fetchall()

        # Grouper par nombre de frameworks
        by_framework_count = {}
        for row in distribution_result:
            key = str(row.nb_frameworks)
            if key not in by_framework_count:
                by_framework_count[key] = 0
            by_framework_count[key] += 1

        # Top PCs les plus réutilisés
        top_pcs_query = text("""
            SELECT
                cp.code,
                cp.name,
                COUNT(DISTINCT f.id) as nb_frameworks,
                COUNT(DISTINCT rcp.requirement_id) as nb_requirements,
                STRING_AGG(DISTINCT f.code, ', ' ORDER BY f.code) as frameworks
            FROM control_point cp
            JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
            JOIN requirement r ON r.id = rcp.requirement_id
            JOIN framework f ON f.id = r.framework_id
            GROUP BY cp.id, cp.code, cp.name
            ORDER BY COUNT(DISTINCT rcp.requirement_id) DESC
            LIMIT 10
        """)

        top_pcs_result = db.execute(top_pcs_query).fetchall()
        top_pcs = [
            {
                "code": row.code,
                "name": row.name,
                "nb_frameworks": row.nb_frameworks,
                "nb_requirements": row.nb_requirements,
                "frameworks": row.frameworks
            }
            for row in top_pcs_result
        ]

        # Économie réalisée
        economy_query = text("""
            SELECT
                COUNT(DISTINCT rcp.requirement_id) as total_requirements,
                COUNT(DISTINCT cp.id) as total_pcs,
                COUNT(DISTINCT rcp.requirement_id) - COUNT(DISTINCT cp.id) as pcs_saved
            FROM control_point cp
            JOIN requirement_control_point rcp ON rcp.control_point_id = cp.id
        """)

        economy_result = db.execute(economy_query).fetchone()

        return {
            "by_framework_count": by_framework_count,
            "top_reused_pcs": top_pcs,
            "economy": {
                "total_requirements": economy_result.total_requirements if economy_result else 0,
                "total_pcs": economy_result.total_pcs if economy_result else 0,
                "pcs_saved": economy_result.pcs_saved if economy_result else 0,
                "saving_percentage": round(
                    (economy_result.pcs_saved / economy_result.total_requirements * 100)
                    if economy_result and economy_result.total_requirements > 0 else 0,
                    2
                )
            }
        }

    except Exception as e:
        print(f"Error in statistics: {e}")
        import traceback
        traceback.print_exc()
        return {
            "by_framework_count": {},
            "top_reused_pcs": [],
            "economy": {
                "total_requirements": 0,
                "total_pcs": 0,
                "pcs_saved": 0,
                "saving_percentage": 0
            }
        }


@router.get("/frameworks")
@cache_result(ttl=1800, key_prefix="cross_ref_frameworks")  # ✅ Cache 30min
async def get_frameworks_for_filter(db: Session = Depends(get_db)):
    """
    Liste des frameworks pour les filtres
    """
    try:
        query = text("""
            SELECT DISTINCT f.id, f.code, f.name
            FROM framework f
            JOIN requirement r ON r.framework_id = f.id
            JOIN requirement_control_point rcp ON rcp.requirement_id = r.id
            WHERE f.is_active = true
            ORDER BY f.code
        """)
        result = db.execute(query)

        frameworks = [
            {
                "id": str(row.id),
                "code": row.code,
                "name": row.name
            }
            for row in result.fetchall()
        ]

        return {"frameworks": frameworks}

    except Exception as e:
        print(f"Error in get_frameworks_for_filter: {e}")
        return {"frameworks": []}
