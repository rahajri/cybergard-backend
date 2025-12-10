#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de test des contrôles SaaS pour l'API Organizations
Teste l'isolation multi-tenant, RBAC, et super-admin
"""
import asyncio
import sys
import os
from pathlib import Path

# Fix Windows encoding issues
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    os.environ['PYTHONIOENCODING'] = 'utf-8'

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session
import uuid
from datetime import datetime
import json

# Import models
from src.database import get_db, engine
from src.models.tenant import Tenant
from src.models.organization import Organization
from src.models.audit import User
from src.models.role import Role, user_role

# Colors for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_header(text: str):
    """Print colored header"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{text:^80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 80}{Colors.RESET}\n")

def print_test(test_id: str, description: str):
    """Print test header"""
    print(f"{Colors.BOLD}{Colors.BLUE}[TEST {test_id}]{Colors.RESET} {description}")

def print_pass(message: str):
    """Print pass message"""
    print(f"  {Colors.GREEN}✅ PASS{Colors.RESET}: {message}")

def print_fail(message: str):
    """Print fail message"""
    print(f"  {Colors.RED}❌ FAIL{Colors.RESET}: {message}")

def print_info(message: str):
    """Print info message"""
    print(f"  {Colors.YELLOW}ℹ️  INFO{Colors.RESET}: {message}")

def print_warning(message: str):
    """Print warning message"""
    print(f"  {Colors.MAGENTA}⚠️  WARN{Colors.RESET}: {message}")

# Test data storage
test_data = {
    'tenant_a_id': None,
    'tenant_b_id': None,
    'org_a1_id': None,
    'org_a2_id': None,
    'org_b1_id': None,
    'org_b2_id': None,
    'super_admin_id': None,
    'tenant_a_admin_id': None,
    'tenant_b_admin_id': None,
    'orphan_user_id': None,
    'revoked_user_id': None,
}

def setup_test_data():
    """Create test data: tenants, organizations, users"""
    print_header("SETUP: Creating Test Data")

    db = next(get_db())

    try:
        # 1. Create Tenants
        print_test("SETUP-1", "Creating test tenants")

        # Tenant A
        tenant_a = db.execute(
            select(Tenant).where(Tenant.name == "Test Tenant A")
        ).scalar_one_or_none()

        if not tenant_a:
            tenant_a = Tenant(
                id=uuid.uuid4(),
                name="Test Tenant A",
                is_active=True,
                subscription_type="professional",
                max_users=10,
                max_organizations=5
            )
            db.add(tenant_a)
            db.flush()
            print_pass(f"Created Tenant A: {tenant_a.id}")
        else:
            print_info(f"Tenant A already exists: {tenant_a.id}")

        test_data['tenant_a_id'] = tenant_a.id

        # Tenant B
        tenant_b = db.execute(
            select(Tenant).where(Tenant.name == "Test Tenant B")
        ).scalar_one_or_none()

        if not tenant_b:
            tenant_b = Tenant(
                id=uuid.uuid4(),
                name="Test Tenant B",
                is_active=True,
                subscription_type="enterprise",
                max_users=50,
                max_organizations=20
            )
            db.add(tenant_b)
            db.flush()
            print_pass(f"Created Tenant B: {tenant_b.id}")
        else:
            print_info(f"Tenant B already exists: {tenant_b.id}")

        test_data['tenant_b_id'] = tenant_b.id

        # 2. Create Organizations
        print_test("SETUP-2", "Creating test organizations")

        # Org A1
        org_a1 = db.execute(
            select(Organization).where(
                Organization.name == "Test Org A1",
                Organization.tenant_id == tenant_a.id
            )
        ).scalar_one_or_none()

        if not org_a1:
            org_a1 = Organization(
                id=uuid.uuid4(),
                name="Test Org A1",
                tenant_id=tenant_a.id,
                subscription_type="professional",
                is_active=True,
                workforce=50
            )
            db.add(org_a1)
            db.flush()
            print_pass(f"Created Org A1: {org_a1.id}")
        else:
            print_info(f"Org A1 already exists: {org_a1.id}")

        test_data['org_a1_id'] = org_a1.id

        # Org A2
        org_a2 = db.execute(
            select(Organization).where(
                Organization.name == "Test Org A2",
                Organization.tenant_id == tenant_a.id
            )
        ).scalar_one_or_none()

        if not org_a2:
            org_a2 = Organization(
                id=uuid.uuid4(),
                name="Test Org A2",
                tenant_id=tenant_a.id,
                subscription_type="starter",
                is_active=False,
                workforce=10
            )
            db.add(org_a2)
            db.flush()
            print_pass(f"Created Org A2: {org_a2.id}")
        else:
            print_info(f"Org A2 already exists: {org_a2.id}")

        test_data['org_a2_id'] = org_a2.id

        # Org B1
        org_b1 = db.execute(
            select(Organization).where(
                Organization.name == "Test Org B1",
                Organization.tenant_id == tenant_b.id
            )
        ).scalar_one_or_none()

        if not org_b1:
            org_b1 = Organization(
                id=uuid.uuid4(),
                name="Test Org B1",
                tenant_id=tenant_b.id,
                subscription_type="enterprise",
                is_active=True,
                workforce=200
            )
            db.add(org_b1)
            db.flush()
            print_pass(f"Created Org B1: {org_b1.id}")
        else:
            print_info(f"Org B1 already exists: {org_b1.id}")

        test_data['org_b1_id'] = org_b1.id

        # Org B2
        org_b2 = db.execute(
            select(Organization).where(
                Organization.name == "Test Org B2",
                Organization.tenant_id == tenant_b.id
            )
        ).scalar_one_or_none()

        if not org_b2:
            org_b2 = Organization(
                id=uuid.uuid4(),
                name="Test Org B2",
                tenant_id=tenant_b.id,
                subscription_type="professional",
                is_active=True,
                workforce=75
            )
            db.add(org_b2)
            db.flush()
            print_pass(f"Created Org B2: {org_b2.id}")
        else:
            print_info(f"Org B2 already exists: {org_b2.id}")

        test_data['org_b2_id'] = org_b2.id

        # 3. Ensure roles exist
        print_test("SETUP-3", "Ensuring roles exist")

        roles_to_create = [
            ("SUPER_ADMIN", "Super Administrateur", True),
            ("CHEF_PROJET", "Chef de Projet", True),
            ("RSSI", "RSSI", True),
            ("AUDITEUR", "Auditeur", True),
        ]

        for role_code, role_name, is_system in roles_to_create:
            role = db.execute(
                select(Role).where(Role.code == role_code)
            ).scalar_one_or_none()

            if not role:
                role = Role(
                    id=uuid.uuid4(),
                    code=role_code,
                    name=role_name,
                    is_system=is_system
                )
                db.add(role)
                print_pass(f"Created role: {role_code}")
            else:
                print_info(f"Role already exists: {role_code}")

        db.flush()

        # 4. Create Test Users
        print_test("SETUP-4", "Creating test users")

        # Get roles
        super_admin_role = db.execute(
            select(Role).where(Role.code == "SUPER_ADMIN")
        ).scalar_one()

        chef_projet_role = db.execute(
            select(Role).where(Role.code == "CHEF_PROJET")
        ).scalar_one()

        auditeur_role = db.execute(
            select(Role).where(Role.code == "AUDITEUR")
        ).scalar_one()

        # Super-admin user
        super_admin = db.execute(
            select(User).where(User.email == "super-admin@test.local")
        ).scalar_one_or_none()

        if not super_admin:
            super_admin = User(
                id=uuid.uuid4(),
                email="super-admin@test.local",
                first_name="Super",
                last_name="Admin",
                tenant_id=None,  # NULL tenant
                is_active=True,
                password_hash="fake_hash",
                keycloak_id="super-admin-kc-id"
            )
            db.add(super_admin)
            db.flush()

            # Assign SUPER_ADMIN role
            db.execute(
                user_role.insert().values(
                    user_id=super_admin.id,
                    role_id=super_admin_role.id,
                    assigned_at=datetime.utcnow()
                )
            )
            print_pass(f"Created Super-Admin: {super_admin.id}")
        else:
            print_info(f"Super-Admin already exists: {super_admin.id}")

        test_data['super_admin_id'] = super_admin.id

        # Tenant A Admin
        tenant_a_admin = db.execute(
            select(User).where(User.email == "admin-a@test.local")
        ).scalar_one_or_none()

        if not tenant_a_admin:
            tenant_a_admin = User(
                id=uuid.uuid4(),
                email="admin-a@test.local",
                first_name="Admin",
                last_name="Tenant A",
                tenant_id=tenant_a.id,
                is_active=True,
                password_hash="fake_hash",
                keycloak_id="admin-a-kc-id"
            )
            db.add(tenant_a_admin)
            db.flush()

            # Assign CHEF_PROJET role
            db.execute(
                user_role.insert().values(
                    user_id=tenant_a_admin.id,
                    role_id=chef_projet_role.id,
                    assigned_at=datetime.utcnow()
                )
            )
            print_pass(f"Created Tenant A Admin: {tenant_a_admin.id}")
        else:
            print_info(f"Tenant A Admin already exists: {tenant_a_admin.id}")

        test_data['tenant_a_admin_id'] = tenant_a_admin.id

        # Tenant B Admin
        tenant_b_admin = db.execute(
            select(User).where(User.email == "admin-b@test.local")
        ).scalar_one_or_none()

        if not tenant_b_admin:
            tenant_b_admin = User(
                id=uuid.uuid4(),
                email="admin-b@test.local",
                first_name="Admin",
                last_name="Tenant B",
                tenant_id=tenant_b.id,
                is_active=True,
                password_hash="fake_hash",
                keycloak_id="admin-b-kc-id"
            )
            db.add(tenant_b_admin)
            db.flush()

            # Assign CHEF_PROJET role
            db.execute(
                user_role.insert().values(
                    user_id=tenant_b_admin.id,
                    role_id=chef_projet_role.id,
                    assigned_at=datetime.utcnow()
                )
            )
            print_pass(f"Created Tenant B Admin: {tenant_b_admin.id}")
        else:
            print_info(f"Tenant B Admin already exists: {tenant_b_admin.id}")

        test_data['tenant_b_admin_id'] = tenant_b_admin.id

        # Orphan user (NULL tenant, no SUPER_ADMIN role)
        orphan_user = db.execute(
            select(User).where(User.email == "orphan@test.local")
        ).scalar_one_or_none()

        if not orphan_user:
            orphan_user = User(
                id=uuid.uuid4(),
                email="orphan@test.local",
                first_name="Orphan",
                last_name="User",
                tenant_id=None,  # NULL tenant but no super-admin role
                is_active=True,
                password_hash="fake_hash",
                keycloak_id="orphan-kc-id"
            )
            db.add(orphan_user)
            db.flush()

            # Assign only AUDITEUR role (NOT SUPER_ADMIN)
            db.execute(
                user_role.insert().values(
                    user_id=orphan_user.id,
                    role_id=auditeur_role.id,
                    assigned_at=datetime.utcnow()
                )
            )
            print_pass(f"Created Orphan User: {orphan_user.id}")
        else:
            print_info(f"Orphan User already exists: {orphan_user.id}")

        test_data['orphan_user_id'] = orphan_user.id

        # Revoked user (will have roles removed later)
        revoked_user = db.execute(
            select(User).where(User.email == "revoked@test.local")
        ).scalar_one_or_none()

        if not revoked_user:
            revoked_user = User(
                id=uuid.uuid4(),
                email="revoked@test.local",
                first_name="Revoked",
                last_name="User",
                tenant_id=tenant_a.id,
                is_active=True,
                password_hash="fake_hash",
                keycloak_id="revoked-kc-id"
            )
            db.add(revoked_user)
            db.flush()

            # Assign CHEF_PROJET role (will be revoked)
            db.execute(
                user_role.insert().values(
                    user_id=revoked_user.id,
                    role_id=chef_projet_role.id,
                    assigned_at=datetime.utcnow()
                )
            )
            print_pass(f"Created Revoked User: {revoked_user.id}")
        else:
            print_info(f"Revoked User already exists: {revoked_user.id}")

        test_data['revoked_user_id'] = revoked_user.id

        db.commit()
        print_pass("All test data created successfully!")

        return test_data

    except Exception as e:
        db.rollback()
        print_fail(f"Error creating test data: {e}")
        raise
    finally:
        db.close()


def test_user_model_methods():
    """Test User model helper methods"""
    print_header("TEST GROUP: User Model Methods")

    db = next(get_db())

    try:
        # Test 1: Super-admin check
        print_test("MODEL-1", "is_super_admin() requires both NULL tenant AND SUPER_ADMIN role")

        super_admin = db.get(User, test_data['super_admin_id'])
        orphan_user = db.get(User, test_data['orphan_user_id'])
        tenant_admin = db.get(User, test_data['tenant_a_admin_id'])

        if super_admin.is_super_admin():
            print_pass(f"Super-admin correctly identified: {super_admin.email}")
        else:
            print_fail(f"Super-admin not recognized: {super_admin.email}")

        if not orphan_user.is_super_admin():
            print_pass(f"Orphan user (NULL tenant, no role) correctly rejected: {orphan_user.email}")
        else:
            print_fail(f"Orphan user incorrectly recognized as super-admin: {orphan_user.email}")

        if not tenant_admin.is_super_admin():
            print_pass(f"Tenant admin correctly not super-admin: {tenant_admin.email}")
        else:
            print_fail(f"Tenant admin incorrectly recognized as super-admin: {tenant_admin.email}")

        # Test 2: Role checks
        print_test("MODEL-2", "has_role() and has_any_role() work correctly")

        if super_admin.has_role("SUPER_ADMIN"):
            print_pass("Super-admin has SUPER_ADMIN role")
        else:
            print_fail("Super-admin missing SUPER_ADMIN role")

        if tenant_admin.has_role("CHEF_PROJET"):
            print_pass("Tenant admin has CHEF_PROJET role")
        else:
            print_fail("Tenant admin missing CHEF_PROJET role")

        if tenant_admin.has_any_role("CHEF_PROJET", "RSSI"):
            print_pass("has_any_role() works correctly")
        else:
            print_fail("has_any_role() not working")

        # Test 3: Get role codes
        print_test("MODEL-3", "get_role_codes() returns correct roles")

        super_admin_roles = super_admin.get_role_codes()
        if "SUPER_ADMIN" in super_admin_roles:
            print_pass(f"Super-admin roles: {super_admin_roles}")
        else:
            print_fail(f"Super-admin roles missing SUPER_ADMIN: {super_admin_roles}")

    finally:
        db.close()


def test_rbac_helper():
    """Test _check_organization_permission helper function"""
    print_header("TEST GROUP: RBAC Helper Function")

    db = next(get_db())

    try:
        from src.api.v1.organizations import _check_organization_permission

        super_admin = db.get(User, test_data['super_admin_id'])
        tenant_admin = db.get(User, test_data['tenant_a_admin_id'])
        orphan_user = db.get(User, test_data['orphan_user_id'])

        # Test 1: Super-admin bypasses all checks
        print_test("RBAC-1", "Super-admin bypasses permission checks")

        try:
            _check_organization_permission(super_admin, "read")
            _check_organization_permission(super_admin, "create")
            _check_organization_permission(super_admin, "update")
            _check_organization_permission(super_admin, "delete")
            _check_organization_permission(super_admin, "export")
            print_pass("Super-admin bypasses all permission checks")
        except Exception as e:
            print_fail(f"Super-admin blocked: {e}")

        # Test 2: Tenant admin with CHEF_PROJET can do all operations
        print_test("RBAC-2", "Tenant admin (CHEF_PROJET) has full permissions")

        try:
            _check_organization_permission(tenant_admin, "read")
            _check_organization_permission(tenant_admin, "create")
            _check_organization_permission(tenant_admin, "update")
            _check_organization_permission(tenant_admin, "delete")
            _check_organization_permission(tenant_admin, "export")
            print_pass("Tenant admin has full CRUD permissions")
        except Exception as e:
            print_fail(f"Tenant admin blocked: {e}")

        # Test 3: Orphan user (NULL tenant, no SUPER_ADMIN role) is blocked
        print_test("RBAC-3", "Orphan user (NULL tenant, no SUPER_ADMIN role) is blocked")

        try:
            _check_organization_permission(orphan_user, "read")
            print_fail("Orphan user was NOT blocked (security issue!)")
        except Exception as e:
            if "Accès interdit" in str(e):
                print_pass(f"Orphan user correctly blocked: {e}")
            else:
                print_fail(f"Orphan user blocked with unexpected error: {e}")

    finally:
        db.close()


def test_tenant_isolation():
    """Test tenant isolation in database queries"""
    print_header("TEST GROUP: Tenant Isolation")

    db = next(get_db())

    try:
        from src.api.v1.organizations import _check_organization_permission

        tenant_a_admin = db.get(User, test_data['tenant_a_admin_id'])

        # Test 1: Tenant admin can only see own organizations
        print_test("ISOLATION-1", "Tenant A admin can only query Tenant A organizations")

        # Simulate what LIST endpoint does
        tenant_a_orgs = db.execute(
            select(Organization).where(Organization.tenant_id == tenant_a_admin.tenant_id)
        ).scalars().all()

        tenant_a_org_ids = [org.id for org in tenant_a_orgs]

        if test_data['org_a1_id'] in tenant_a_org_ids and test_data['org_a2_id'] in tenant_a_org_ids:
            print_pass(f"Tenant A admin sees Tenant A organizations: {len(tenant_a_orgs)} orgs")
        else:
            print_fail("Tenant A admin missing own organizations")

        if test_data['org_b1_id'] not in tenant_a_org_ids and test_data['org_b2_id'] not in tenant_a_org_ids:
            print_pass("Tenant A admin does NOT see Tenant B organizations")
        else:
            print_fail("CRITICAL: Tenant A admin can see Tenant B organizations!")

        # Test 2: Super-admin can see all organizations
        print_test("ISOLATION-2", "Super-admin can see all organizations")

        super_admin = db.get(User, test_data['super_admin_id'])

        # Super-admin query (no tenant filter)
        all_orgs = db.execute(
            select(Organization).where(
                Organization.id.in_([
                    test_data['org_a1_id'],
                    test_data['org_a2_id'],
                    test_data['org_b1_id'],
                    test_data['org_b2_id']
                ])
            )
        ).scalars().all()

        if len(all_orgs) == 4:
            print_pass(f"Super-admin sees all 4 test organizations")
        else:
            print_fail(f"Super-admin only sees {len(all_orgs)} organizations (expected 4)")

        # Test 3: Cross-tenant GET simulation
        print_test("ISOLATION-3", "Tenant A admin cannot GET Tenant B organization")

        # Simulate GET with tenant filtering
        cross_tenant_org = db.execute(
            select(Organization).where(
                Organization.id == test_data['org_b1_id'],
                Organization.tenant_id == tenant_a_admin.tenant_id  # Wrong tenant
            )
        ).scalar_one_or_none()

        if cross_tenant_org is None:
            print_pass("Cross-tenant GET correctly returns None (will be 404)")
        else:
            print_fail("CRITICAL: Cross-tenant organization accessible!")

    finally:
        db.close()


def test_role_revocation():
    """Test role revocation by simulating role sync"""
    print_header("TEST GROUP: Role Revocation")

    db = next(get_db())

    try:
        from src.dependencies_keycloak import _sync_user_roles_from_keycloak

        revoked_user = db.get(User, test_data['revoked_user_id'])

        # Test 1: User initially has role
        print_test("REVOKE-1", "User initially has CHEF_PROJET role")

        initial_roles = revoked_user.get_role_codes()
        if "CHEF_PROJET" in initial_roles:
            print_pass(f"User has initial roles: {initial_roles}")
        else:
            print_fail(f"User missing CHEF_PROJET role: {initial_roles}")

        # Test 2: Simulate Keycloak role revocation (empty roles)
        print_test("REVOKE-2", "Simulate Keycloak returning empty roles list")

        _sync_user_roles_from_keycloak(db, revoked_user, [])  # Empty roles from Keycloak

        db.refresh(revoked_user)
        after_revoke_roles = revoked_user.get_role_codes()

        if len(after_revoke_roles) == 0:
            print_pass("All roles successfully revoked")
        else:
            print_fail(f"CRITICAL: User still has roles after revocation: {after_revoke_roles}")

        # Test 3: Verify RBAC blocks revoked user
        print_test("REVOKE-3", "Revoked user cannot access organizations")

        from src.api.v1.organizations import _check_organization_permission

        try:
            _check_organization_permission(revoked_user, "read")
            print_fail("CRITICAL: Revoked user can still access organizations!")
        except Exception as e:
            if "Permissions insuffisantes" in str(e):
                print_pass(f"Revoked user correctly blocked: {e}")
            else:
                print_fail(f"Revoked user blocked with unexpected error: {e}")

        # Test 4: Re-assign role
        print_test("REVOKE-4", "Re-assign role and verify access restored")

        _sync_user_roles_from_keycloak(db, revoked_user, ["chef_projet"])

        db.refresh(revoked_user)
        restored_roles = revoked_user.get_role_codes()

        if "CHEF_PROJET" in restored_roles:
            print_pass(f"Role successfully restored: {restored_roles}")
        else:
            print_fail(f"Role not restored: {restored_roles}")

        try:
            _check_organization_permission(revoked_user, "read")
            print_pass("User can access organizations after role restoration")
        except Exception as e:
            print_fail(f"User still blocked after role restoration: {e}")

    finally:
        db.close()


def test_statistics_rbac():
    """Test statistics endpoints RBAC and super-admin support"""
    print_header("TEST GROUP: Statistics RBAC")

    db = next(get_db())

    try:
        from src.api.v1.organizations import _check_organization_permission
        from sqlalchemy import func

        super_admin = db.get(User, test_data['super_admin_id'])
        tenant_a_admin = db.get(User, test_data['tenant_a_admin_id'])

        # Test 1: Tenant admin sees only own tenant stats
        print_test("STATS-1", "Tenant A admin sees only Tenant A statistics")

        # Simulate stats/overview endpoint logic
        tenant_a_count = db.scalar(
            select(func.count(Organization.id)).where(
                Organization.tenant_id == tenant_a_admin.tenant_id
            )
        ) or 0

        if tenant_a_count == 2:  # org_a1 + org_a2
            print_pass(f"Tenant A admin sees 2 organizations (correct)")
        else:
            print_fail(f"Tenant A admin sees {tenant_a_count} organizations (expected 2)")

        # Test 2: Super-admin sees global stats
        print_test("STATS-2", "Super-admin sees global statistics (all tenants)")

        # Simulate super-admin stats query (no tenant filter)
        global_count = db.scalar(
            select(func.count(Organization.id)).where(
                Organization.id.in_([
                    test_data['org_a1_id'],
                    test_data['org_a2_id'],
                    test_data['org_b1_id'],
                    test_data['org_b2_id']
                ])
            )
        ) or 0

        if global_count == 4:
            print_pass(f"Super-admin sees 4 organizations globally (correct)")
        else:
            print_fail(f"Super-admin sees {global_count} organizations (expected 4)")

        # Test 3: Super-admin can filter by specific tenant
        print_test("STATS-3", "Super-admin can filter stats by specific tenant")

        # Simulate super-admin with tenant_id filter
        filtered_count = db.scalar(
            select(func.count(Organization.id)).where(
                Organization.tenant_id == test_data['tenant_b_id']
            )
        ) or 0

        if filtered_count == 2:  # org_b1 + org_b2
            print_pass(f"Super-admin filtered by Tenant B sees 2 organizations (correct)")
        else:
            print_fail(f"Super-admin filtered by Tenant B sees {filtered_count} organizations (expected 2)")

    finally:
        db.close()


def print_test_summary():
    """Print test summary"""
    print_header("TEST SUMMARY")

    print(f"{Colors.BOLD}Test Data Created:{Colors.RESET}")
    print(f"  • Tenant A ID: {test_data['tenant_a_id']}")
    print(f"  • Tenant B ID: {test_data['tenant_b_id']}")
    print(f"  • Org A1 ID: {test_data['org_a1_id']}")
    print(f"  • Org A2 ID: {test_data['org_a2_id']}")
    print(f"  • Org B1 ID: {test_data['org_b1_id']}")
    print(f"  • Org B2 ID: {test_data['org_b2_id']}")
    print(f"  • Super-Admin ID: {test_data['super_admin_id']}")
    print(f"  • Tenant A Admin ID: {test_data['tenant_a_admin_id']}")
    print(f"  • Tenant B Admin ID: {test_data['tenant_b_admin_id']}")
    print(f"  • Orphan User ID: {test_data['orphan_user_id']}")
    print(f"  • Revoked User ID: {test_data['revoked_user_id']}")

    print(f"\n{Colors.BOLD}Next Steps:{Colors.RESET}")
    print(f"  1. Review test results above")
    print(f"  2. If all tests pass, proceed with HTTP API tests using curl/Postman")
    print(f"  3. Test with real Keycloak tokens")
    print(f"  4. Run full test suite from TESTING_SAAS_CONTROLS.md")

    print(f"\n{Colors.BOLD}{Colors.GREEN}All database-level tests completed!{Colors.RESET}\n")


def main():
    """Main test runner"""
    try:
        # Setup
        setup_test_data()

        # Run test groups
        test_user_model_methods()
        test_rbac_helper()
        test_tenant_isolation()
        test_role_revocation()
        test_statistics_rbac()

        # Summary
        print_test_summary()

    except Exception as e:
        print_fail(f"Test execution failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
