"""Deployment readiness contract tests."""

from scripts.pre_deploy import deployment_report


def test_deployment_report_exposes_web_interface_and_python_runtime() -> None:
    report = deployment_report(
        configuration_valid=True,
        database_integrity=True,
        python_version=(3, 11),
    )

    assert report["active_interface"] == "web_ui"
    assert report["python_311"] is True
    assert "telegram" not in repr(report).lower()


def test_deployment_report_rejects_python_runtime_drift() -> None:
    report = deployment_report(
        configuration_valid=True,
        database_integrity=True,
        python_version=(3, 12),
    )

    assert report["python_311"] is False
