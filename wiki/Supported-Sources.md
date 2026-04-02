# Supported Sources

| Source               | Strategy                                                                         |
| -------------------- | -------------------------------------------------------------------------------- |
| GitBook sites        | `--provider gitbook`: `/llms-full.txt` → `/llms.txt`                             |
| Mintlify sites       | `--provider mintlify` or `auto`: `/llms-full.txt` → `/llms.txt` → `/sitemap.xml` |
| Generic web docs     | `--provider web`: generic crawler for non-GitBook / non-Mintlify sites           |
| Local `.md` / `.txt` | Read from disk                                                                   |

When using `auto` (the default), docmancer tries to detect the provider automatically based on the site's response headers and content.
