import time
import os


def generate_id(prefix: str) -> str:
    ts_hex = format(int(time.time() * 1000), "x")
    rand_hex = os.urandom(4).hex()
    return f"{prefix}_{ts_hex}_{rand_hex}"


def generate_goal_id() -> str:
    return generate_id("goal")


def generate_task_id() -> str:
    return generate_id("task")


def generate_archive_id() -> str:
    return generate_id("archive")


def generate_pattern_id() -> str:
    return generate_id("pat")


def generate_evolution_id() -> str:
    return generate_id("evo")


def generate_fix_session_id() -> str:
    return generate_id("fix")


def generate_feedback_id() -> str:
    return generate_id("fb")


def generate_project_id() -> str:
    return generate_id("proj")


def generate_phase_gate_id() -> str:
    return generate_id("pg")


def generate_phase_history_id() -> str:
    return generate_id("ph")
