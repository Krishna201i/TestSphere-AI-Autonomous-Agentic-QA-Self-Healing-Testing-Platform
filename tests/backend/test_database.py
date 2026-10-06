"""
TestSphere-AI — Member 3 Database Model & Relationship Tests.

Validates:
1. Project model creation and persistence.
2. Application linkage to Project.
3. TestCase linkage to Application.
4. TestExecution linkage to TestCase.
5. Bidirectional relationships and cascade behavior.
6. Required field constraints (NOT NULL).
7. Database tables initialization.
"""

import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base, init_db
from backend.models import (
    Application,
    Project,
    TestCase,
    TestExecution,
    TestExecutionStatus,
)


class TestDatabaseModels(unittest.TestCase):
    """Test suite for Member 3 database persistence models."""

    def setUp(self) -> None:
        """Create an isolated in-memory SQLite database and session factory."""
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session = self.Session()

    def tearDown(self) -> None:
        """Clean up session and drop all tables."""
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_database_tables_initialization(self) -> None:
        """Verify that all Member 3 tables are successfully created in the schema."""
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        self.assertIn("projects", tables)
        self.assertIn("applications", tables)
        self.assertIn("test_cases", tables)
        self.assertIn("test_executions", tables)

    def test_create_project(self) -> None:
        """Verify Project model can be created, persisted, and retrieved."""
        project = Project(
            name="E-Commerce QA Suite",
            description="End-to-end testing project for store application",
        )
        self.session.add(project)
        self.session.commit()

        self.assertIsNotNone(project.id)
        self.assertEqual(project.name, "E-Commerce QA Suite")
        self.assertEqual(project.description, "End-to-end testing project for store application")
        self.assertIsNotNone(project.created_at)
        self.assertIsNotNone(project.updated_at)

    def test_link_application_to_project(self) -> None:
        """Verify Application can be linked to a Project with bidirectional navigation."""
        project = Project(name="CRM Project")
        self.session.add(project)
        self.session.commit()

        app = Application(
            project_id=project.id,
            name="CRM Web Frontend",
            base_url="https://crm.example.com",
            description="Main customer web portal",
        )
        self.session.add(app)
        self.session.commit()

        # Refresh and verify relationship
        self.session.refresh(project)
        self.assertEqual(len(project.applications), 1)
        self.assertEqual(project.applications[0].name, "CRM Web Frontend")
        self.assertEqual(app.project.id, project.id)

    def test_link_test_case_to_application(self) -> None:
        """Verify TestCase can be linked to an Application."""
        project = Project(name="Analytics App Project")
        app = Application(
            name="Dashboard UI",
            base_url="https://dashboard.example.com",
            project=project,
        )
        self.session.add_all([project, app])
        self.session.commit()

        tc = TestCase(
            application_id=app.id,
            external_id="tc-login-001",
            name="Valid User Login",
            description="Verify login flow with valid credentials",
            category="AUTHENTICATION",
            priority="CRITICAL",
            version=1,
        )
        self.session.add(tc)
        self.session.commit()

        self.session.refresh(app)
        self.assertEqual(len(app.test_cases), 1)
        self.assertEqual(app.test_cases[0].external_id, "tc-login-001")
        self.assertEqual(tc.application.name, "Dashboard UI")
        self.assertEqual(tc.version, 1)

    def test_link_test_execution_to_test_case(self) -> None:
        """Verify TestExecution can be linked to a TestCase and status defaults properly."""
        project = Project(name="Billing System")
        app = Application(
            name="Checkout Portal",
            base_url="https://checkout.example.com",
            project=project,
        )
        tc = TestCase(
            name="Stripe Payment Flow",
            application=app,
        )
        self.session.add_all([project, app, tc])
        self.session.commit()

        execution = TestExecution(
            test_case_id=tc.id,
            status=TestExecutionStatus.RUNNING.value,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(execution)
        self.session.commit()

        self.session.refresh(tc)
        self.assertEqual(len(tc.test_executions), 1)
        self.assertEqual(tc.test_executions[0].status, TestExecutionStatus.RUNNING.value)
        self.assertEqual(execution.test_case.name, "Stripe Payment Flow")

    def test_full_relationship_chain_and_cascade(self) -> None:
        """Verify Project -> Application -> TestCase -> TestExecution navigation and cascade delete."""
        project = Project(name="Root Project")
        app = Application(name="Portal", base_url="https://portal.test", project=project)
        tc = TestCase(name="Checkout Test", application=app)
        execution = TestExecution(test_case=tc, status=TestExecutionStatus.PASSED.value, duration_ms=450)

        self.session.add_all([project, app, tc, execution])
        self.session.commit()

        # Traverse full chain forward
        self.assertEqual(len(project.applications), 1)
        self.assertEqual(len(project.applications[0].test_cases), 1)
        self.assertEqual(len(project.applications[0].test_cases[0].test_executions), 1)
        self.assertEqual(project.applications[0].test_cases[0].test_executions[0].status, "PASSED")

        # Verify cascade delete from Project level
        project_id = project.id
        self.session.delete(project)
        self.session.commit()

        self.assertIsNone(self.session.get(Project, project_id))
        self.assertEqual(self.session.query(Application).count(), 0)
        self.assertEqual(self.session.query(TestCase).count(), 0)
        self.assertEqual(self.session.query(TestExecution).count(), 0)

    def test_required_fields_constraints(self) -> None:
        """Verify NOT NULL constraints on required fields for all models."""
        # 1. Project requires name
        with self.subTest("Project requires name"):
            proj = Project(name=None)  # type: ignore
            self.session.add(proj)
            with self.assertRaises(IntegrityError):
                self.session.commit()
            self.session.rollback()

        # 2. Application requires name and base_url
        with self.subTest("Application requires name and base_url"):
            valid_proj = Project(name="Valid Project")
            self.session.add(valid_proj)
            self.session.commit()

            app_no_url = Application(project_id=valid_proj.id, name="App", base_url=None)  # type: ignore
            self.session.add(app_no_url)
            with self.assertRaises(IntegrityError):
                self.session.commit()
            self.session.rollback()

        # 3. TestCase requires name and application_id
        with self.subTest("TestCase requires name"):
            tc_no_name = TestCase(application_id=1, name=None)  # type: ignore
            self.session.add(tc_no_name)
            with self.assertRaises(IntegrityError):
                self.session.commit()
            self.session.rollback()

        # 4. TestExecution requires test_case_id
        with self.subTest("TestExecution requires test_case_id"):
            exec_no_tc = TestExecution(test_case_id=None, status="PENDING")  # type: ignore
            self.session.add(exec_no_tc)
            with self.assertRaises(IntegrityError):
                self.session.commit()
            self.session.rollback()

    def test_init_db_helper_execution(self) -> None:
        """Verify the init_db() helper function executes cleanly."""
        result = init_db()
        self.assertTrue(result)
        # Dispose default engine to release Windows file lock before cleanup
        from backend.database.session import engine as default_engine
        default_engine.dispose()
        import os
        if os.path.exists("testsphere.db"):
            try:
                os.remove("testsphere.db")
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
