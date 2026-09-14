# Auto Notification

A workflow that decides whether a message is routine or needs a paper trail, then
delivers it to Slack or email.

## What it does

1. Takes a free-text message.
2. `parameter-extractor` pulls out a `channel` decision (`slack` or `email`) and a short
   `subject`, with the instruction "routine → slack, needs a paper trail → email".
3. `if-else` branches on `channel`.
4. One of two `http-request` nodes delivers the message — Slack webhook, or an email API.
5. `variable-aggregator` collapses whichever branch ran into a single status for `end`.

## Graph

```
start ─> extract_route (parameter-extractor) ─> if_channel (if-else)
                                                 ├─ ⟨email⟩ ─> http_email ─┐
                                                 └─ ⟨false⟩ ─> http_slack ─┤
                                                                          └─> agg_status ─> end
```

7 nodes, 7 edges. `mode: workflow`.

## Files

- `dsl.yml` — the DSL, ready to import (Dify 1.17, `version: 0.7.0`)
- `README.md` — this file

## Setup

1. **Import** `dsl.yml`: Studio → Create from blank (workflow) → save → `...` → Import DSL File.
2. **Fill in the environment variables** (`...` → Environment Variables). The DSL ships
   with placeholders and one `secret`:

   | Variable | Value |
   |---|---|
   | `EMAIL_API_URL` | your transactional email endpoint |
   | `EMAIL_API_KEY` | your token (`value_type: secret`) |
   | `NOTIFY_EMAIL` | recipient address |
   | `SLACK_WEBHOOK` | Slack incoming webhook URL |

3. **Configure the model** used by `判断渠道` — it defaults to `gpt-4o-mini` at
   `temperature: 0`. Use a small, fast, JSON-reliable model; this is a classification
   step, not a reasoning step.
4. Test with a routine message and with something that needs a record.

## Test cases

| Input | Expected |
|---|---|
| "Deploy finished, all green" | `channel: slack`, Slack receives the text, `status` is the HTTP status code |
| "We need written confirmation of the SLA change for the audit file" | `channel: email`, email is sent |
| An ambiguous message | Falls to a channel, but check `subject` — a vague subject means the instruction needs tightening |

## Notes

- `agg_status` merges `http_email.status_code` and `http_slack.status_code`. Numbers are
  safe to aggregate: the branch that did not run produces an empty value which the
  aggregator skips. **Do not aggregate arrays this way** — an empty array counts as a
  non-empty value and will mask the real result (`../../references/pitfalls.md` §2).
- The HTTP nodes set a `timeout` block. Leave it in; a hung endpoint otherwise stalls the run.
- Credentials are never in the file. `EMAIL_API_KEY` is a `secret` environment variable,
  and it is blanked on export — re-enter it after any round trip through a file.
