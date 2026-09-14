# External services

Notifications, webhooks, and third-party APIs all go through the `http-request` node
(or a `tool` node when a plugin already wraps the service). This file gives the real
node shape and working recipes for the common destinations.

## The `http-request` node

```yaml
- data:
    type: http-request
    title: 发送通知
    desc: ''
    selected: false
    method: post                    # get post put patch delete head options
    url: '{{env.SLACK_WEBHOOK}}'    # {{env.X}} and {{#node.key#}} both work
    authorization:
      type: no-auth                 # no-auth | api-key  (bearer/basic go in headers)
      config: null
    headers: |                      # REQUIRED, raw string, "" if unused
      Content-Type: application/json
      Authorization: Bearer {{env.API_TOKEN}}
    params: ''                      # REQUIRED, raw query string, "" if unused
    body:
      type: json                    # none json form-data x-www-form-urlencoded raw-text binary
      data:
        - key: text
          value: '{{#start.message#}}'
          type: text                # text | variable  (variable rows use a [node,key] value)
    timeout:
      connect: 10
      read: 30
      write: 10
```

Things that trip people up:

- **`headers` and `params` are required strings.** Both must be present; use `""` when
  there is nothing to send. An absent key fails node validation.
- **Only `no-auth` and `api-key` exist.** There is no `bearer` or `basic` type — put a
  `Bearer` / `Basic` value in `headers` instead. `api-key` puts the key in a header or
  query param configured in `config`.
- **Credentials go through `{{env.X}}`.** Declare them under
  `workflow.environment_variables` with `value_type: secret`.
- **`body.data` rows are either literal text or a variable.** A `text` row
  interpolates `{{#node.key#}}`; a `variable` row stores a `[node, key]` selector in
  `value`.
- **Outputs:** `body` · `status_code` · `headers` · `files`. `body` is a string;
  `json.loads` it in a code node if you need structure.
- **Always set a timeout** on third-party calls. Without one, a hung endpoint stalls
  the whole workflow.

## Headers you will actually write

```yaml
# Bearer token
headers: |-
  Authorization: Bearer {{env.API_TOKEN}}
  Content-Type: application/json

# Basic auth
headers: |-
  Authorization: Basic {{env.BASIC_CREDENTIALS}}
  Content-Type: application/x-www-form-urlencoded

# API key in a custom header (e.g. SendGrid, Anthropic-style)
headers: |-
  X-Api-Key: {{env.SERVICE_API_KEY}}
  Content-Type: application/json
```

`{{env.BASIC_CREDENTIALS}}` should hold the pre-encoded `base64(user:password)` value —
compute it outside Dify rather than embedding credentials in the DSL.

## Notification recipes

### Slack incoming webhook

```yaml
- data:
    type: http-request
    title: Slack
    desc: ''
    selected: false
    method: post
    url: '{{env.SLACK_WEBHOOK}}'
    authorization: {type: no-auth, config: null}
    headers: 'Content-Type: application/json'
    params: ''
    body:
      type: json
      data:
        - {key: text, value: '[{{#extract_alert.severity#}}] {{#extract_alert.summary#}}', type: text}
```

### Feishu / Lark custom bot

```yaml
    body:
      type: json
      data:
        - {key: msg_type, value: text, type: text}
        - {key: content, value: '{"text": "{{#extract_alert.summary#}}"}', type: text}
```

### DingTalk custom robot

```yaml
    body:
      type: json
      data:
        - {key: msgtype, value: text, type: text}
        - {key: text, value: '{"content": "{{#extract_alert.summary#}}"}', type: text}
```

DingTalk robots that use a signed secret need two extra fields; compute `timestamp` and
`sign` in a `code` node first (HMAC-SHA256 over `timestamp\nsecret`) and pass them as
body rows — the sandbox allows `hmac` and `hashlib` from the standard library.

### WeCom (企业微信) group robot

```yaml
    body:
      type: json
      data:
        - {key: msgtype, value: markdown, type: text}
        - {key: markdown, value: '{''content'': ''{{#extract_alert.summary#}}''}', type: text}
```

### Transactional email (SendGrid-shaped)

```yaml
- data:
    type: http-request
    title: 邮件
    desc: ''
    selected: false
    method: post
    url: '{{env.EMAIL_API_URL}}'
    authorization: {type: no-auth, config: null}
    headers: |-
      Authorization: Bearer {{env.EMAIL_API_KEY}}
      Content-Type: application/json
    params: ''
    body:
      type: json
      data:
        - {key: to, value: '{{env.ONCALL_EMAIL}}', type: text}
        - {key: subject, value: '[{{#extract_alert.severity#}}] {{#extract_alert.service#}}', type: text}
        - {key: body, value: '{{#build_report.output#}}', type: text}
    timeout: {connect: 10, read: 30, write: 10}
```

### SMS gateway

Most Chinese SMS gateways want form-encoded parameters and a signature computed from
the parameter string. Build the signature in a `code` node and send
`type: x-www-form-urlencoded`:

```yaml
    headers: 'Content-Type: application/x-www-form-urlencoded'
    body:
      type: x-www-form-urlencoded
      data:
        - {key: phone, value: '{{env.ONCALL_PHONE}}', type: text}
        - {key: content, value: '{{#extract_alert.summary#}}', type: text}
        - {key: sign, value: '{{#code_signature.output#}}', type: text}
```

## Fan-out pattern

Route first, then call. One `if-else` on the extracted severity, several HTTP nodes as
the branch targets, and a `variable-aggregator` to collapse the branch results for the
`end` node:

```
start → parameter-extractor → if-else(severe / medium / else)
        severe ├→ http_sms      ┐
               └→ http_dingtalk ┤
       medium  ├→ http_email    ├→ variable-aggregator → end
               └→ http_feishu   ┤
        else   └→ http_slack    ┘
```

Two details that decide whether this works:

- The aggregator returns the **first non-empty** value, and `[]` counts as non-empty
  while a number or string from a non-executed branch is empty. Aggregating
  `status_code` (a number) or `body` (a string) from branches that may not have run is
  safe; aggregating arrays is not. See `pitfalls.md` §2.
- Branch nodes that did not execute produce no output at all. Do not reference a
  branch-specific output from a node that runs unconditionally on the other branch.

## Webhook receivers (inbound)

To *receive* webhooks, add a `trigger-webhook` node as the graph entry instead of
`start`. Note that the generated `webhook_url` is cleared on export and re-issued on
import, so the URL must be re-read from the UI after importing — a trigger-based
workflow is not fully reproducible from a file.

## Calling another Dify app

Two options:

1. A `tool` node of `provider_type: workflow` (or `app`), pointing at the published
   workflow/app. Preferred — Dify handles auth and payload shape.
2. An `http-request` node against that app's service API:

```yaml
    method: post
    url: '{{env.OTHER_APP_ENDPOINT}}/workflows/run'
    headers: |-
      Authorization: Bearer {{env.OTHER_APP_KEY}}
      Content-Type: application/json
    body:
      type: json
      data:
        - {key: inputs, value: '{"contract_text": "{{#start.contract_text#}}"}', type: text}
        - {key: response_mode, value: blocking, type: text}
        - {key: user, value: dify-workflow, type: text}
```

Chain this pattern when one workflow needs another's judgment — for example generating a
document and then calling a separate audit workflow on it. It also lets the audit stay
independently versioned and tested.

## Debugging an HTTP node

| Symptom | Likely cause |
|---|---|
| Node refuses to validate | `headers` or `params` key missing |
| 401 / 403 | credential not in `headers` (no `bearer` auth type exists), or the secret env var is blank after import |
| 400 from the provider | body row typed `text` but the provider wants JSON, or a nested JSON string has unescaped quotes |
| Workflow hangs | no `timeout` on the node |
| Works in the UI, fails in API runs | secret env var was blanked by `include_secret=false` on export and never re-entered |
