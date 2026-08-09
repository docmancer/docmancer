"""Transcript evidence consolidation command."""
from __future__ import annotations

import json
from pathlib import Path

import click

from docmancer.cli.help import DocmancerCommand, HELP_CONTEXT_SETTINGS


@click.command("consolidate", cls=DocmancerCommand, context_settings=HELP_CONTEXT_SETTINGS, short_help="Find reviewable memory atoms in Claude Code and Codex histories.")
@click.option("--project", default=None, help="Limit scanning to one project path, name, or portable id.")
@click.option("--dry-run", is_flag=True, help="Show candidates and cost without saving proposals.")
@click.option("--review", "review_id", default=None, metavar="PROPOSAL", help="Show one source-attributed proposal.")
@click.option("--approve", "approve_id", default=None, metavar="PROPOSAL", help="Apply one reviewed proposal as a memory atom.")
@click.option("--reject", "reject_id", default=None, metavar="PROPOSAL", help="Reject one proposal and suppress unchanged evidence.")
@click.option("--text", "replacement_text", default=None, help="Edit proposal wording while approving it.")
@click.option("--provider", "provider_id", default=None, help="Use one configured BYOK provider on bounded redacted candidate clusters.")
@click.option("--model", default=None, help="Override the configured provider model for this run.")
@click.option("--yes", is_flag=True, help="Confirm the displayed provider payload without prompting.")
@click.option("--json", "as_json", is_flag=True)
@click.option("--home", type=click.Path(path_type=Path, file_okay=False), hidden=True)
@click.option("--state-root", type=click.Path(path_type=Path, file_okay=False), hidden=True)
def consolidate_cmd(
    project: str | None,
    dry_run: bool,
    review_id: str | None,
    approve_id: str | None,
    reject_id: str | None,
    replacement_text: str | None,
    provider_id: str | None,
    model: str | None,
    yes: bool,
    as_json: bool,
    home: Path | None,
    state_root: Path | None,
) -> None:
    """Select transcript evidence locally and require review before apply."""
    from docmancer.transcripts import TranscriptConsolidator

    selected = sum(bool(value) for value in (review_id, approve_id, reject_id))
    if selected > 1:
        raise click.UsageError("choose only one of --review, --approve, or --reject")
    if replacement_text and not approve_id:
        raise click.UsageError("--text requires --approve")
    if model and not provider_id:
        raise click.UsageError("--model requires --provider")
    if provider_id and selected:
        raise click.UsageError("--provider is available only when creating proposals")
    service = TranscriptConsolidator(root=state_root, home=home)
    try:
        if review_id:
            value = service.proposal(review_id)
            if value is None:
                raise ValueError("transcript proposal not found")
        elif approve_id:
            value = service.approve(approve_id, text=replacement_text)
        elif reject_id:
            value = service.reject(reject_id)
        else:
            if provider_id:
                preview = service.scan(
                    project=project,
                    dry_run=True,
                    provider_id=provider_id,
                    model=model,
                )
                if dry_run:
                    value = preview
                else:
                    message = (
                        f"Send {preview['candidate_spans']} redacted candidate span(s), "
                        f"about {preview['provider_characters']:,} characters and "
                        f"{preview['provider_tokens']:,} input tokens, to {provider_id}"
                    )
                    if not yes and not click.confirm(message + "?", default=False):
                        raise click.Abort()
                    value = service.scan(
                        project=project,
                        provider_id=provider_id,
                        model=model,
                    )
            else:
                value = service.scan(project=project, dry_run=dry_run)
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(value, indent=2, ensure_ascii=False))
        return
    if review_id:
        _show_proposal(value)
        return
    if approve_id:
        click.echo(f"Applied {value['proposal_id']} as memory atom {value['record_id']}.")
        return
    if reject_id:
        click.echo(f"Rejected {value['proposal_id']}. Unchanged evidence will not be proposed again.")
        return
    click.echo(
        f"Scanned {value['sessions_scanned']} changed sessions ({value['bytes_scanned']:,} bytes); "
        f"found {value['candidate_spans']} candidate spans in {value['clusters']} clusters."
    )
    click.echo(
        f"Provider use: {value['provider_characters']:,} characters, "
        f"about {value['provider_tokens']:,} input tokens, "
        f"${float(value['provider_cost']):.4f} reported cost."
    )
    for proposal in value.get("items", [])[:20]:
        if proposal.get("proposal_id"):
            click.echo(f"\n{proposal['proposal_id']}  {proposal['memory_type']}  sources={len(proposal['evidence'])}")
            click.echo(proposal["text"])
        else:
            click.echo(f"\n[dry run] {proposal['memory_type']}  recurrence={proposal['recurrence']}")
            click.echo(proposal["text"])
    if not dry_run and value.get("items"):
        click.echo("\nReview one with: docmancer consolidate --review PROPOSAL")


def _show_proposal(value: dict) -> None:
    click.echo(f"{value['proposal_id']}  state={value['state']}  type={value['memory_type']}")
    click.echo(value["text"])
    if value.get("wording") == "provider-assisted":
        click.echo(f"Wording: provider-assisted via {value.get('provider')} {value.get('model')}")
    click.echo("\nEvidence:")
    for source in value["evidence"]:
        click.echo(f"- {source['agent']} {source['session_path']} byte {source['byte_offset']} record {source['record_hash'][:12]}")
    if value["state"] == "pending":
        click.echo(f"\nApply only after review: docmancer consolidate --approve {value['proposal_id']}")


__all__ = ["consolidate_cmd"]
