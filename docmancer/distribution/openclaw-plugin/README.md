# Docmancer for OpenClaw

This plugin uses OpenClaw's native `before_prompt_build` hook to request bounded, cited context from the installed local `docmancer` CLI. The Python core remains authoritative, plaintext stays local, and failures are fail-open.

The operator must allow prompt injection for this trusted local plugin:

```json
{
  "plugins": {
    "entries": {
      "docmancer": {
        "enabled": true,
        "hooks": { "allowPromptInjection": true },
        "config": { "tokenBudget": 2000 }
      }
    }
  }
}
```

Verify a local install with `openclaw plugins inspect docmancer --runtime --json` after restarting the Gateway.
