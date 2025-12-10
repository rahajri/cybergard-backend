#!/usr/bin/env python3
"""
Script pour initialiser l'écosystème de base d'un client
Usage: python -m src.scripts.seed_ecosystem --client-org acme_corp
"""

import sys
import argparse
from uuid import uuid4
from datetime import datetime

# Ajouter le chemin du projet
sys.path.insert(0, '.')

from sqlalchemy.orm import Session
from src.database import SessionLocal, engine
from src.models.ecosystem import EcosystemEntity, EntityStatus


def seed_ecosystem(client_organization_id: str, tenant_id: str = None):
    """Initialise l'écosystème de base"""
    
    db = SessionLocal()
    
    try:
        # Générer tenant_id si non fourni
        if not tenant_id:
            tenant_id = str(uuid4())
        
        print(f"\n🚀 Initialisation écosystème pour client: {client_organization_id}")
        print(f"📋 Tenant ID: {tenant_id}")
        
        # ====================================================================
        # 1. DOMAINES
        # ====================================================================
        
        # Domaine INTERNE
        internal_domain = EcosystemEntity(
            id=uuid4(),
            tenant_id=tenant_id,
            client_organization_id=client_organization_id,
            name="Interne",
            stakeholder_type="internal",
            is_category=True,
            entity_category="domain",
            hierarchy_level=1,
            status=EntityStatus.ACTIVE,
            is_active=True,
            country_code="FR"
        )
        db.add(internal_domain)
        db.flush()
        print(f"✅ Domaine INTERNE créé : {internal_domain.id}")
        
        # Domaine EXTERNE
        external_domain = EcosystemEntity(
            id=uuid4(),
            tenant_id=tenant_id,
            client_organization_id=client_organization_id,
            name="Externe",
            stakeholder_type="external",
            is_category=True,
            entity_category="domain",
            hierarchy_level=1,
            status=EntityStatus.ACTIVE,
            is_active=True,
            country_code="FR"
        )
        db.add(external_domain)
        db.flush()
        print(f"✅ Domaine EXTERNE créé : {external_domain.id}")
        
        # ====================================================================
        # 2. CATÉGORIES INTERNES
        # ====================================================================
        
        internal_categories = [
            {"name": "Pôle IT", "category": "pole"},
            {"name": "Pôle RH", "category": "pole"},
            {"name": "Pôle Finance", "category": "pole"},
        ]
        
        for cat_data in internal_categories:
            category = EcosystemEntity(
                id=uuid4(),
                tenant_id=tenant_id,
                client_organization_id=client_organization_id,
                name=cat_data["name"],
                stakeholder_type="internal",
                is_category=True,
                entity_category=cat_data["category"],
                parent_entity_id=internal_domain.id,
                hierarchy_level=2,
                status=EntityStatus.ACTIVE,
                is_active=True,
                country_code="FR"
            )
            db.add(category)
            print(f"✅ Catégorie INTERNE créée : {cat_data['name']}")
        
        db.flush()
        
        # ====================================================================
        # 3. CATÉGORIES EXTERNES
        # ====================================================================
        
        external_categories = [
            {"name": "Clients", "category": "clients"},
            {"name": "Fournisseurs", "category": "fournisseurs"},
        ]
        
        for cat_data in external_categories:
            category = EcosystemEntity(
                id=uuid4(),
                tenant_id=tenant_id,
                client_organization_id=client_organization_id,
                name=cat_data["name"],
                stakeholder_type="external",
                is_category=True,
                entity_category=cat_data["category"],
                parent_entity_id=external_domain.id,
                hierarchy_level=2,
                status=EntityStatus.ACTIVE,
                is_active=True,
                country_code="FR"
            )
            db.add(category)
            print(f"✅ Catégorie EXTERNE créée : {cat_data['name']}")
        
        db.commit()
        
        print(f"\n🎉 Écosystème initialisé avec succès pour {client_organization_id}")
        print(f"📊 Structure créée :")
        print(f"   • 2 domaines (Interne, Externe)")
        print(f"   • 3 catégories internes (Pôle IT, RH, Finance)")
        print(f"   • 2 catégories externes (Clients, Fournisseurs)")
        
    except Exception as e:
        db.rollback()
        print(f"\n❌ Erreur lors de l'initialisation : {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialiser l'écosystème de base")
    parser.add_argument(
        "--client-org",
        required=True,
        help="ID de l'organisation cliente (ex: acme_corp)"
    )
    parser.add_argument(
        "--tenant-id",
        help="UUID du tenant (optionnel, généré automatiquement si non fourni)"
    )
    
    args = parser.parse_args()
    
    seed_ecosystem(
        client_organization_id=args.client_org,
        tenant_id=args.tenant_id
    )