.PHONY: help demo test test-backend lint sarif

help:
	@echo "TestSphere AI — Autonomous Agentic QA & Self-Healing Testing Platform"
	@echo ""
	@echo "Available Targets:"
	@echo "  demo          Run the end-to-end vulnerable demo app & full autonomous QA/security loop"
	@echo "  test          Run full test suite"
	@echo "  test-backend  Run fast backend, agent, and security test suites"
	@echo "  lint          Run code linter (ruff)"
	@echo "  sarif         Scan demo app and generate SARIF v2.1.0 report"

demo:
	python3 backend/scripts/run_demo.py

test:
	cd backend && python3 -m pytest -q

test-backend:
	cd backend && python3 -m pytest -q tests/app tests/security tests/test_*.py

lint:
	ruff check backend

sarif:
	python3 backend/scripts/run_demo.py --sarif-only
