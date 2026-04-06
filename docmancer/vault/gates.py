"""Pre-publish quality gates for vault packages."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from docmancer.vault.lint import LintIssue, lint_vault


@dataclass
class GateResult:
    """Quality gate results."""

    passed: bool = True
    lint_issues: list[LintIssue] = field(default_factory=list)
    eval_result: dict | None = None
    critical_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_pre_publish_gates(
    vault_root: Path,
    *,
    eval_threshold_mrr: float = 0.3,
    eval_threshold_hit_rate: float = 0.5,
    block_on_errors: bool = True,
) -> GateResult:
    """Run all quality gates before publishing.

    1. Run vault lint (deterministic checks)
    2. If golden dataset exists, run eval
    3. Block if critical lint errors and block_on_errors is True
    4. Warn if eval scores below threshold
    """
    result = GateResult()

    # Run lint
    try:
        issues = lint_vault(vault_root)
        result.lint_issues = issues

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]

        if errors:
            result.critical_errors.append(
                f"Lint found {len(errors)} error(s): "
                + "; ".join(f"{e.check}: {e.path}" for e in errors[:5])
            )
        if warnings:
            result.warnings.append(
                f"Lint found {len(warnings)} warning(s)."
            )
    except Exception as exc:
        result.warnings.append(f"Lint check failed: {exc}")

    # Run eval if golden dataset exists
    eval_dataset_path = vault_root / ".docmancer" / "eval_dataset.json"
    if eval_dataset_path.exists():
        try:
            from docmancer.eval.dataset import EvalDataset
            from docmancer.eval.runner import run_eval
            from docmancer.core.config import DocmancerConfig
            from docmancer.agent import DocmancerAgent

            ds = EvalDataset.load(eval_dataset_path)
            filled = [e for e in ds.entries if e.question]

            if filled:
                config_path = vault_root / "docmancer.yaml"
                if config_path.exists():
                    config = DocmancerConfig.from_yaml(config_path)
                else:
                    config = DocmancerConfig()

                agent = DocmancerAgent(config=config)
                eval_res = run_eval(ds, query_fn=agent.query, k=5)
                result.eval_result = eval_res.to_dict()

                if eval_res.mrr < eval_threshold_mrr:
                    result.warnings.append(
                        f"MRR ({eval_res.mrr:.4f}) is below threshold ({eval_threshold_mrr})."
                    )
                if eval_res.hit_rate < eval_threshold_hit_rate:
                    result.warnings.append(
                        f"Hit Rate ({eval_res.hit_rate:.4f}) is below threshold ({eval_threshold_hit_rate})."
                    )
        except Exception as exc:
            result.warnings.append(f"Eval check failed: {exc}")

    # Determine pass/fail
    if block_on_errors and result.critical_errors:
        result.passed = False

    return result
