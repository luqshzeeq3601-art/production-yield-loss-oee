"""Persistent local PostgreSQL 16 startup, serving load, and live validation.

Run with py -3.11 -m scripts.bootstrap_powerbi_db [prepare|start|load|check|stop].
Binaries must already exist at --bin-dir (vendor Windows archive by default).
No pgserver server lifecycle, random port, password output, or Desktop launch.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn, make_dsn
import yaml

from src import cross_system_reconciliation, load_db, run_dq_checks
from src.config_loader import load_config
from src.powerbi_serving import ROOT, load_evidence, validate_live, validate_spc_evidence

LOCAL = ROOT / ".local"
ENV_KEYS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "DATABASE_URL")


def load_environment(path: Path) -> None:
    """Read the project's explicit local .env; process environment takes priority.

    Supports KEY=value and simple quoted values, without shell evaluation.
    """
    if not path.is_file():
        raise ValueError("Local environment file missing; run the start command first")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator and key.strip() in ENV_KEYS:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def _restrict(path: Path) -> None:
    if os.name == "nt":
        account = f"{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}"
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:F", "SYSTEM:F"],
                       check=True, capture_output=True)
    else:
        path.chmod(0o600)


def _command(arguments: list[str], *, check=True):
    if "start" in arguments:
        # Windows children may inherit pipe handles: use a log, not communicate().
        with (LOCAL / "pg-control.log").open("a", encoding="utf-8") as output:
            result = subprocess.run(arguments, stdout=output, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if check and result.returncode:
            raise RuntimeError("pg_ctl start failed; inspect .local/pg-control.log")
        return result
    result = subprocess.run(arguments, capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check and result.returncode:
        # Commands carry paths only; database passwords never enter command args.
        raise RuntimeError(f"{Path(arguments[0]).name} failed: {result.stderr.strip()}")
    return result


def start_database(bin_dir: Path, env_file: Path) -> None:
    bin_dir = bin_dir.resolve()
    pg_ctl = bin_dir / ("pg_ctl.exe" if os.name == "nt" else "pg_ctl")
    initdb = bin_dir / ("initdb.exe" if os.name == "nt" else "initdb")
    if not pg_ctl.is_file() or not initdb.is_file():
        raise ValueError("PostgreSQL binaries missing; follow the connection checklist installation step")
    version = _command([str(pg_ctl), "--version"]).stdout.strip()
    if " 16." not in version:
        raise ValueError("PostgreSQL 16 binaries required")
    data_dir = LOCAL / "pgdata"
    LOCAL.mkdir(exist_ok=True)
    if not env_file.exists():
        if (data_dir / "PG_VERSION").exists():
            raise ValueError("Existing cluster has no credential file; restore its .env before starting")
        env_file.write_text(
            "POSTGRES_HOST=127.0.0.1\nPOSTGRES_PORT=5432\nPOSTGRES_DB=production_yield_oee\n"
            f"POSTGRES_USER=powerbi_local\nPOSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n",
            encoding="utf-8",
        )
        _restrict(env_file)
    load_environment(env_file)
    db = parse_dsn(load_db._resolve_dsn(load_config()))
    if db.get("host") not in {"127.0.0.1", "localhost"}:
        raise ValueError("Managed startup supports loopback only")
    port = int(db.get("port", 5432))
    status = _command([str(pg_ctl), "-D", str(data_dir), "status"], check=False)
    if status.returncode != 0:
        with socket.socket() as probe:
            if probe.connect_ex((db["host"], port)) == 0:
                raise ValueError(f"Port {port} is already occupied; configure a stable free port in .env")
        if not (data_dir / "PG_VERSION").exists():
            pwfile = LOCAL / "initdb-password.tmp"
            try:
                pwfile.write_text(db["password"] + "\n", encoding="utf-8")
                _restrict(pwfile)
                _command([str(initdb), "-D", str(data_dir), "-U", db["user"],
                          "--pwfile", str(pwfile), "-A", "scram-sha-256", "-E", "UTF8", "--locale=C"])
            finally:
                pwfile.unlink(missing_ok=True)
            with (data_dir / "postgresql.conf").open("a", encoding="utf-8") as out:
                out.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\n")
        _command([str(pg_ctl), "-D", str(data_dir), "-l", str(LOCAL / "postgresql.log"), "-w", "-t", "60", "start"])
    admin = psycopg2.connect(make_dsn(**(db | {"dbname": "postgres"})), connect_timeout=5)
    try:
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db["dbname"],))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db["dbname"])))
    finally:
        admin.close()
    print(f"{version}; persistent cluster started at {db['host']}:{port}/{db['dbname']}")


def prepare(action: str, bin_dir: Path, env_file: Path, full_analytics: bool) -> dict:
    if action in {"prepare", "load", "check", "stop"}:
        path = ROOT / "reports/powerbi_readiness.json"
        if path.is_file():
            path.write_text(json.dumps({"task": "POWERBI-PREP", "status": "CHECKING"}) + "\n", encoding="utf-8")
    if action in {"start", "prepare"}:
        start_database(bin_dir, env_file)
    else:
        load_environment(env_file)
    if action == "stop":
        _command([str(bin_dir / "pg_ctl.exe"), "-D", str(LOCAL / "pgdata"), "-w", "stop"])
        (ROOT / "reports/powerbi_readiness.json").write_text(
            json.dumps({"task": "POWERBI-PREP", "status": "STOPPED"}) + "\n", encoding="utf-8",
        )
        return {"status": "STOPPED"}
    config = load_config()
    report_dir = LOCAL / "powerbi-live"
    report_dir.mkdir(parents=True, exist_ok=True)
    config["paths"]["reports"] = str(report_dir)
    config_path = report_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    dsn = load_db._resolve_dsn(config)
    if action != "start":
        validate_spc_evidence(ROOT / "reports", ROOT / config["secom"]["outputs"]["cleaned_data"])
    if action in {"load", "prepare"}:
        load_db.run(config_path, powerbi_only=not full_analytics)
    if action == "start":
        with closing(psycopg2.connect(dsn, connect_timeout=5)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                if cur.fetchone()[0] != 1:
                    raise ValueError("Connection test failed")
        return {"status": "STARTED", "select_one": 1}
    dq = run_dq_checks.run(config_path, powerbi_only=not full_analytics)
    if dq["failed_checks"] or dq["total_violations"]:
        raise ValueError("Live warehouse DQ failed; inspect .local/powerbi-live/dq_check_summary.json")
    # All 75 comparisons use committed source/report evidence; live probe is supplemental.
    reconciliation = cross_system_reconciliation.run()
    if reconciliation["fail_count"] or not reconciliation["database_live"]["available"]:
        raise ValueError("Reconciliation or its live connection probe failed")
    with closing(psycopg2.connect(dsn, connect_timeout=5)) as conn:
        evidence_counts = load_evidence(conn, ROOT / "reports", dq)
        live = validate_live(conn, config_path)
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port(), current_setting('server_version')")
            database, user, host, port, version = cur.fetchone()
    result = {
        "task": "POWERBI-PREP", "status": "READY", "python_version": sys.version.split()[0],
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable, "database": {"host": host, "port": port,
        "name": database, "user": user, "version": version, "credential_source": ".env or process environment",
        "database_url_source": "process/.env override" if os.environ.get("DATABASE_URL") else "not set; POSTGRES_* variables"},
        "warehouse_profile": "full_analytics" if full_analytics else "powerbi",
        "metropt_readings_required_for_powerbi": False, "powerbi_desktop_opened": False,
        "dq": {k: dq[k] for k in ("total_checks", "passed_checks", "failed_checks", "total_violations", "excluded_checks")},
        "reconciliation": {"checks": reconciliation["total_checks"], "passed": reconciliation["pass_count"],
                           "basis": "75 artifact comparisons; supplemental live aggregate probe", "database_live": reconciliation["database_live"]},
        "evidence_rows": evidence_counts, "live_validation": live,
    }
    (ROOT / "reports/powerbi_readiness.json").write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    print(f"POWER BI ASSEMBLY READY = YES; {len(live['pages'])}/7 page dependencies resolved live")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="prepare", choices=("prepare", "start", "load", "check", "stop"))
    parser.add_argument("--bin-dir", type=Path, default=LOCAL / "postgresql16/pgsql/bin")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--full-analytics", action="store_true", help="also load/validate MetroPT readings; not required for Desktop")
    args = parser.parse_args(argv)
    try:
        prepare(args.action, args.bin_dir, args.env_file, args.full_analytics)
    except Exception as exc:
        message = str(exc)
        for key in ("POSTGRES_PASSWORD", "DATABASE_URL"):
            if os.environ.get(key):
                message = message.replace(os.environ[key], "[REDACTED_SECRET]")
        print(f"Power BI preparation FAILED ({type(exc).__name__}): {message}", file=sys.stderr)
        path = ROOT / "reports/powerbi_readiness.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"task": "POWERBI-PREP", "status": "BLOCKED", "error": message}) + "\n", encoding="utf-8")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
