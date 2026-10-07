"""
TestSphere-AI — Database Seeder.

Populates initial database records for Projects, Applications, Test Cases,
and Test Executions when the platform starts up with an empty database.
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from backend.models.project import Project
from backend.models.application import Application
from backend.models.test_case import TestCase
from backend.models.test_execution import TestExecution, TestExecutionStatus


def seed_database_if_empty(db: Session) -> bool:
    """Seed initial records if the projects table is currently empty."""
    if db.query(Project).count() > 0:
        return False

    now = datetime.now(timezone.utc)

    # 1. Projects
    proj1 = Project(
        name="E-Commerce Webapp",
        description="Customer-facing online storefront, product catalog, cart, and payment checkout pipelines.",
        created_at=now - timedelta(days=5),
        updated_at=now,
    )
    proj2 = Project(
        name="FinTech Core Banking Portal",
        description="Retail and corporate banking services, funds transfer, authentication MFA, and ledger reconciliation.",
        created_at=now - timedelta(days=4),
        updated_at=now,
    )
    proj3 = Project(
        name="Healthcare Patient Portal",
        description="HIPAA-compliant appointments, doctor-patient telemedicine chat, and medical records dashboard.",
        created_at=now - timedelta(days=3),
        updated_at=now,
    )
    db.add_all([proj1, proj2, proj3])
    db.commit()
    db.refresh(proj1)
    db.refresh(proj2)
    db.refresh(proj3)

    # 2. Applications
    app1 = Application(
        project_id=proj1.id,
        name="E-Commerce Storefront",
        base_url="https://example.com",
        description="Online shopping storefront and product catalog interface",
        created_at=now - timedelta(days=5),
        updated_at=now,
    )
    app2 = Application(
        project_id=proj1.id,
        name="Cart & Payment Checkout Flow",
        base_url="https://example.com/checkout",
        description="End-to-end shopping cart checkout and order payment gateway",
        created_at=now - timedelta(days=5),
        updated_at=now,
    )
    app3 = Application(
        project_id=proj2.id,
        name="Authentication & SSO Gateway",
        base_url="https://example.com/auth",
        description="User login, multi-factor authentication, and JWT authorization",
        created_at=now - timedelta(days=4),
        updated_at=now,
    )
    app4 = Application(
        project_id=proj3.id,
        name="Customer Account Portal",
        base_url="https://example.com/account",
        description="Account settings, profile details, and telemedicine schedule",
        created_at=now - timedelta(days=3),
        updated_at=now,
    )
    db.add_all([app1, app2, app3, app4])
    db.commit()
    db.refresh(app1)
    db.refresh(app2)
    db.refresh(app3)
    db.refresh(app4)

    # 3. Test Cases
    tc1 = TestCase(
        application_id=app1.id,
        external_id="TC_LOGIN_001",
        name="User Login & Auth Flow",
        description='{"steps": [{"action": "NAVIGATE", "value": "https://example.com/login"}, {"action": "FILL", "target": "#username", "value": "testuser"}, {"action": "CLICK", "target": "#login-btn"}]}',
        category="Authentication",
        priority="High",
        version=1,
        created_at=now - timedelta(days=2),
        updated_at=now,
    )
    tc2 = TestCase(
        application_id=app1.id,
        external_id="TC_CART_002",
        name="Add Item to Cart",
        description='{"steps": [{"action": "NAVIGATE", "value": "https://example.com/products/item-42"}, {"action": "CLICK", "target": "button[data-testid=\\"add-to-cart\\"]"}]}',
        category="E-Commerce",
        priority="High",
        version=1,
        created_at=now - timedelta(days=2),
        updated_at=now,
    )
    tc3 = TestCase(
        application_id=app2.id,
        external_id="TC_CHECKOUT_003",
        name="Complete Checkout Flow",
        description='{"steps": [{"action": "NAVIGATE", "value": "https://example.com/checkout"}, {"action": "CLICK", "target": "#complete-order"}]}',
        category="E-Commerce",
        priority="Medium",
        version=1,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )
    tc4 = TestCase(
        application_id=app1.id,
        external_id="TC_SEARCH_004",
        name="Search Product Catalog",
        description='{"steps": [{"action": "NAVIGATE", "value": "https://example.com"}, {"action": "FILL", "target": "input[type=\\"search\\"]", "value": "headphones"}]}',
        category="Search & Filter",
        priority="Medium",
        version=1,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )
    tc5 = TestCase(
        application_id=app4.id,
        external_id="TC_PROFILE_005",
        name="Update User Profile Info",
        description='{"steps": [{"action": "NAVIGATE", "value": "https://example.com/account"}, {"action": "CLICK", "target": "button#avatar-upload"}]}',
        category="User Account",
        priority="Low",
        version=1,
        created_at=now - timedelta(hours=12),
        updated_at=now,
    )
    db.add_all([tc1, tc2, tc3, tc4, tc5])
    db.commit()
    db.refresh(tc1)
    db.refresh(tc2)
    db.refresh(tc3)
    db.refresh(tc4)
    db.refresh(tc5)

    # 4. Test Executions
    exec1 = TestExecution(
        test_case_id=tc1.id,
        status=TestExecutionStatus.PASSED.value,
        started_at=now - timedelta(minutes=45),
        completed_at=now - timedelta(minutes=42),
        duration_ms=154000,
        error_message=None,
    )
    exec2 = TestExecution(
        test_case_id=tc2.id,
        status=TestExecutionStatus.FAILED.value,
        started_at=now - timedelta(minutes=30),
        completed_at=now - timedelta(minutes=28),
        duration_ms=72000,
        error_message="HTTP 500 Internal Server Error returned by cart backend",
    )
    exec3 = TestExecution(
        test_case_id=tc3.id,
        status=TestExecutionStatus.PASSED.value,
        started_at=now - timedelta(minutes=20),
        completed_at=now - timedelta(minutes=16),
        duration_ms=198000,
        error_message=None,
    )
    exec4 = TestExecution(
        test_case_id=tc4.id,
        status=TestExecutionStatus.PASSED.value,
        started_at=now - timedelta(minutes=10),
        completed_at=now - timedelta(minutes=8),
        duration_ms=105000,
        error_message=None,
    )
    db.add_all([exec1, exec2, exec3, exec4])
    db.commit()

    return True


if __name__ == "__main__":
    from backend.database.session import SessionLocal, init_db
    init_db()
    db_session = SessionLocal()
    seeded = seed_database_if_empty(db_session)
    print(f"Database seeded: {seeded}")
    db_session.close()
