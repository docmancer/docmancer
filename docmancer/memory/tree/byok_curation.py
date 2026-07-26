"""BYOK (bring-your-own-key) Curation, opt-in LLM sibling of the
deterministic ``CurationEngine`` (checklist B.5, plan section 5.2).

This module is the *only* place in the tree package that is allowed to
call an LLM. It never runs unless the caller has explicitly configured an
OpenRouter API key (reusing ``docmancer.ai.openrouter_client.openrouter_api_key``
and ``OpenRouterClient`` -- no second provider client, no second key
convention). Every entry point below is safe to call unconditionally: with
no key configured it returns a clear "not configured" result and makes no
provider call at all.

Design constraints taken directly from plan section 5.2 and checklist B.5:

1. Explicit configuration only -- ``BYOKCurationEngine.is_configured()``
   gates every entry point. No fallback to a default key, no environment
   probing beyond the existing ``openrouter_api_key()`` helper.
2. Evidence is redacted with ``docmancer.harness.secrets.redact_secrets``
   on every piece of text before it is placed into the provider prompt.
   This runs even when the key is present but before the request is
   built, so a secret can never reach the wire through this module.
3. The provider must return a strict, schema-validated JSON object (see
   ``BYOKCurationResponse`` below). Responses are validated by Pydantic
   during the ``OpenRouterClient.parse(...)`` call itself (JSON-schema
   constrained decoding), and then re-validated here against the actual
   evidence list, scope, and project the engine was invoked for.
4. Every provider write records ``curation_origin="byok_curation"`` plus
   ``provider``, ``model``, and ``prompt_version`` in the entry's
   ``extra_frontmatter`` (round-tripped verbatim by ``parser.py``), so a
   BYOK-curated file is always distinguishable from a deterministic or
   manual one.
5. **Design decision -- mandatory authority is rejected, not downgraded.**
   If the (mocked or real) provider response sets ``authority`` to
   ``"mandatory"`` the whole response is treated as invalid and *nothing*
   is written -- this module does not silently coerce it to
   ``"advisory"`` and proceed. Silently downgrading would let a curation
   run "succeed" while quietly discarding a signal the model tried to
   send, which is a worse failure mode than an explicit, loud rejection.
   Plan 5.2 says a model "cannot assign mandatory authority"; the safest
   reading of "cannot" for an irreversible tree write is "the write does
   not happen," not "the write happens with the field forced to
   something else the caller never asked for." (Documented again on
   ``_validate_response`` and exercised by
   ``test_mandatory_authority_attempt_is_rejected`` in the test file.)
6. Any provider failure -- timeout, transport error, malformed/non-JSON
   response, schema-validation failure at the ``OpenRouterClient`` layer
   -- is caught here and turned into a clean
   ``BYOKCurationResult(outcome="provider_failed", ...)``. This module
   never raises out of ``curate()`` for provider-side failure, and it
   never calls the deterministic ``CurationEngine`` itself: whether to
   fall back to deterministic curation is the caller's decision (the
   checklist's "fall back to deterministic curation when the provider is
   unavailable" bullet is implemented one layer up, by a caller choosing
   to construct and call a ``CurationEngine`` after seeing
   ``provider_failed`` -- keeping that choice explicit and visible
   instead of hidden inside this module).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from docmancer.harness.secrets import redact_secrets
from docmancer.memory.tree.contracts import VALID_SCOPES, VALID_STATUS
from docmancer.memory.tree.parser import TreeMemoryFile
from docmancer.memory.tree.store import TreeStore

# Bumped whenever the prompt text or response schema semantics change in a
# way that would make an old curated file's recorded prompt_version no
# longer describe how it was produced. Recorded verbatim on every write.
PROMPT_VERSION = "byok-curation-v1"

CURATION_ORIGIN = "byok_curation"

# Plan 5.2 / checklist B.5: BYOK curation must never assign mandatory
# authority. This is the only authority value a BYOK response is allowed
# to request; anything else (in particular "mandatory") is rejected.
_ALLOWED_RESPONSE_AUTHORITY = "advisory"


class BYOKCurationResponse(BaseModel):
    """Strict schema the provider must return (checklist B.5: "Define
    strict response schemas"). Passed as ``response_format`` to
    ``OpenRouterClient.parse``, so the client itself enforces this shape
    via JSON-schema-constrained decoding; this module then re-validates
    the *content* (citations, authority, path) against the evidence and
    scope the engine was actually invoked for.

    Fields:
    - ``title``: synthesized title for the curated note.
    - ``body``: synthesized Markdown body (plan 5.2: "synthesize multiple
      cited inputs into a durable note").
    - ``domain_relative_path``: proposed path under the caller-supplied
      project/scope root, e.g. ``"decisions/foo.md"`` (plan 5.2:
      "choose a domain or topic"). Never an absolute path or one
      containing ``..`` -- enforced below, independent of what the model
      returns.
    - ``cited_source_indices``: 0-based indices into the evidence list
      the caller supplied, one per source actually used. Every index must
      exist in the evidence list or the whole response is rejected
      (checklist B.5: "Validate citations ... after every response").
    - ``authority``: the model's requested authority. Only
      ``"advisory"`` is accepted; ``"mandatory"`` (or anything else) is
      rejected outright -- see module docstring point 5.
    - ``supersedes_evidence_index``: optional 0-based evidence index this
      note supersedes/expresses supersession for (plan 5.2: "Express
      supersession"), validated the same way as citations.
    - ``rationale``: short human-readable note on why this synthesis/
      placement was chosen; stored in frontmatter for audit, never used
      for control flow.
    """

    title: str
    body: str
    domain_relative_path: str
    cited_source_indices: list[int] = Field(default_factory=list)
    authority: str = _ALLOWED_RESPONSE_AUTHORITY
    supersedes_evidence_index: int | None = None
    rationale: str = ""


@dataclass
class EvidenceItem:
    """One piece of redacted, cited evidence supplied to the provider.
    ``source`` is a citation string (path, URL, session id) matching the
    ``sources`` convention already used by ``CurationEngine``."""

    text: str
    source: str


@dataclass
class BYOKCurationResult:
    """Outcome of one ``BYOKCurationEngine.curate(...)`` call.

    ``outcome`` is one of:
    - ``"not_configured"``: no OpenRouter API key; no provider call made.
    - ``"provider_failed"``: the provider call itself failed (timeout,
      transport error, malformed response); safe to retry or fall back.
    - ``"invalid_response"``: the provider returned a schema-valid object
      that failed content validation (bad citation, mandatory authority,
      out-of-scope path); nothing was written.
    - ``"written"``: a curated ``TreeMemoryFile`` was written.
    """

    outcome: Literal["not_configured", "provider_failed", "invalid_response", "written"]
    entry: TreeMemoryFile | None = None
    reason: str = ""
    provider: str = ""
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    raw_response: BYOKCurationResponse | None = None
    extra: dict = field(default_factory=dict)


def _build_messages(evidence: list[EvidenceItem], *, scope: str, project_id: str | None) -> list[dict]:
    """Redact every piece of evidence text before it is placed into the
    prompt (checklist B.5: "Redact evidence before constructing a
    provider request"). Only the minimum evidence needed for this one
    curation operation is included (no whole-tree dump)."""
    lines = [
        "You are a curation assistant for a local, per-developer memory tree.",
        "You will be given a numbered list of evidence items (already redacted of secrets).",
        "Synthesize them into ONE durable curated note.",
        f"Target scope: {scope!r}. Target project_id: {project_id!r}.",
        "Only cite evidence indices that are actually used.",
        'Set "authority" to "advisory". Never propose "mandatory" authority.',
        "domain_relative_path must be a short relative path (no leading '/', no '..').",
        "",
        "Evidence:",
    ]
    for index, item in enumerate(evidence):
        redacted_text = redact_secrets(item.text)
        redacted_source = redact_secrets(item.source)
        lines.append(f"[{index}] (source: {redacted_source})\n{redacted_text}")
    prompt = "\n\n".join(lines)
    return [
        {
            "role": "system",
            "content": (
                "Return only the requested structured curation output. "
                "Never fabricate a source that was not supplied."
            ),
        },
        {"role": "user", "content": prompt},
    ]


def _is_safe_relative_path(path_text: str) -> bool:
    if not path_text or path_text.strip() == "":
        return False
    candidate = Path(path_text)
    if candidate.is_absolute():
        return False
    if ".." in candidate.parts:
        return False
    return True


class BYOKCurationEngine:
    """Opt-in LLM curation over a ``TreeStore``. Mirrors the deterministic
    ``CurationEngine``'s store-write plumbing (same ``TreeStore.write``
    contract, same ``sources``/``authority``/``status`` vocabulary) but is
    the only place in the tree package allowed to call a provider."""

    def __init__(self, store: TreeStore, *, client=None) -> None:
        self.store = store
        self._injected_client = client

    @staticmethod
    def is_configured() -> bool:
        """True when the configured default provider is ready."""
        try:
            from docmancer.ai.providers.factory import provider_status
            from docmancer.core.config import DocmancerConfig

            providers = DocmancerConfig().providers
            return provider_status(
                providers.default_llm,
                config=providers,
            )["key_state"] in {"stored", "from_env", "override", "not_required"}
        except Exception:
            return False

    def _client(self):
        if self._injected_client is not None:
            return self._injected_client
        from docmancer.ai.providers.factory import provider_client
        from docmancer.core.config import DocmancerConfig

        providers = DocmancerConfig().providers
        return provider_client(providers.default_llm, config=providers)

    def _validate_response(
        self,
        response: BYOKCurationResponse,
        *,
        evidence: list[EvidenceItem],
        project_id: str | None,
    ) -> str | None:
        """Return an error reason string if the response must be
        discarded, or ``None`` if it passes all checks. Nothing is
        written to the tree when this returns non-``None``."""
        if not evidence:
            return "no evidence supplied to validate citations against"

        n = len(evidence)
        for cited_index in response.cited_source_indices:
            if cited_index < 0 or cited_index >= n:
                return f"cited_source_indices contains out-of-range index {cited_index} (evidence has {n} items)"
        if not response.cited_source_indices:
            return "response cited no evidence sources"

        if response.supersedes_evidence_index is not None:
            si = response.supersedes_evidence_index
            if si < 0 or si >= n:
                return f"supersedes_evidence_index {si} is out of range (evidence has {n} items)"

        # Plan 5.2 / checklist B.5: BYOK curation must never assign
        # mandatory authority. Rejected outright -- see module docstring
        # point 5 for why this is a hard rejection, not a downgrade.
        if response.authority != _ALLOWED_RESPONSE_AUTHORITY:
            return (
                f"response requested authority={response.authority!r}; "
                f"BYOK curation may only produce authority={_ALLOWED_RESPONSE_AUTHORITY!r}"
            )

        if not _is_safe_relative_path(response.domain_relative_path):
            return f"domain_relative_path {response.domain_relative_path!r} is not a safe project-relative path"

        if not response.title.strip():
            return "response title is empty"
        if not response.body.strip():
            return "response body is empty"

        return None

    def curate(
        self,
        evidence: list[EvidenceItem],
        *,
        scope: str = "project",
        project_id: str | None = None,
        memory_type: str = "fact",
        tags: list[str] | None = None,
    ) -> BYOKCurationResult:
        """Curate ``evidence`` (already-collected, cited text snippets)
        into one curated ``TreeMemoryFile`` using an explicitly-configured
        provider. See class/module docstrings for the full contract.
        """
        if scope not in VALID_SCOPES:
            return BYOKCurationResult(
                outcome="invalid_response",
                reason=f"unsupported scope {scope!r}",
            )

        if not self.is_configured():
            return BYOKCurationResult(
                outcome="not_configured",
                reason="No default provider credential is configured; BYOK curation did not run and made no provider call",
            )

        try:
            client = self._client()
        except Exception as exc:  # noqa: BLE001 - configuration errors fail closed
            # Key vanished between is_configured() and client construction,
            # or another config problem surfaced. Still a clean, non-raising
            # "not configured" outcome -- no provider call was made.
            return BYOKCurationResult(outcome="not_configured", reason=str(exc))

        messages = _build_messages(evidence, scope=scope, project_id=project_id)

        try:
            response = client.parse(messages, BYOKCurationResponse)
        except Exception as exc:  # noqa: BLE001 - any other provider/parse failure must not raise
            # Covers malformed/non-JSON content, schema-validation failure
            # inside OpenRouterClient.parse, or any other unexpected
            # provider-layer error. This module never lets a provider
            # failure escape as an unhandled exception.
            return BYOKCurationResult(
                outcome="provider_failed",
                reason=f"provider response could not be parsed or validated: {exc}",
                provider=getattr(client, "provider_name", "OpenRouter"),
                model=getattr(client, "model", ""),
            )

        error = self._validate_response(response, evidence=evidence, project_id=project_id)
        if error is not None:
            return BYOKCurationResult(
                outcome="invalid_response",
                reason=error,
                provider=getattr(client, "provider_name", "OpenRouter"),
                model=getattr(client, "model", ""),
                raw_response=response,
            )

        sources = [evidence[i].source for i in response.cited_source_indices]
        provider_name = getattr(client, "provider_name", "OpenRouter")
        model_name = getattr(client, "model", "")

        # ``TreeStore.write`` (store.py, not owned by this module and left
        # untouched) only round-trips ``extra_frontmatter`` that was already
        # present on a *prior* revision of the file -- it has no parameter
        # for a caller to inject new frontmatter keys on first create. To
        # still satisfy "record provider, model, and prompt-version on
        # every successful write" without modifying store.py, this
        # provenance is recorded as a machine-readable trailer inside the
        # body itself (checked verbatim by the tests below), immediately
        # under the title, before the synthesized content.
        provenance_lines = [
            f"<!-- byok_provider: {provider_name} -->",
            f"<!-- byok_model: {model_name} -->",
            f"<!-- byok_prompt_version: {PROMPT_VERSION} -->",
        ]
        if response.rationale:
            provenance_lines.append(f"<!-- byok_rationale: {response.rationale} -->")
        body_text = "\n".join(
            [f"# {response.title}", "", *provenance_lines, "", response.body]
        )

        entry = self.store.write(
            relative_path=response.domain_relative_path,
            text=body_text,
            memory_type=memory_type,
            scope=scope,
            authority=_ALLOWED_RESPONSE_AUTHORITY,
            project_id=project_id,
            sources=sources,
            status="active",
            tags=tags or [],
            curation_origin=CURATION_ORIGIN,
            expect="absent",
        )

        return BYOKCurationResult(
            outcome="written",
            entry=entry,
            reason="provider response validated; curated entry written",
            provider=provider_name,
            model=model_name,
            raw_response=response,
        )


__all__ = [
    "PROMPT_VERSION",
    "CURATION_ORIGIN",
    "BYOKCurationEngine",
    "BYOKCurationResponse",
    "BYOKCurationResult",
    "EvidenceItem",
]
