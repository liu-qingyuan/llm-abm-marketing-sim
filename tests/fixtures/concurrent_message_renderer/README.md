# Concurrent renderer compatibility fixtures

These compressed fixtures are a checked-in regression contract for the persisted
`ConcurrentMessageReportPayload` used by the published Concurrent Formal report.
They contain the typed report payload and exact UTF-8 HTML outputs for the fixed
renderer paths. They do not contain raw prompts, provider requests, provider
responses, credentials, or request headers.

`compatibility_goldens.json` is the source of truth for the fixture schema and
SHA-256 values. The `editorial_v2_default` golden is the current local default
`4e6680caf8476aa2b7839a20a985c320ce423c64b974d592b449ee2afa0ddbd8`.
The frozen `editorial_v1` golden remains the published report hash
`1d1e1ead3691aa275c74ff723a79960019c42fd58f179d8b74619f0a0b218ea9`. The
`pre_pagination_historical` golden is the published source report hash
`740f55a30bc4183a75724592496c6b6aa809a85ab385ccf96bc53093cb49a76d`. The
`current_two_mode` golden is the published destination compatibility report hash
`ba006c5e18d091a77e8eebd73e86287209ccaf2571023d1114e35fd64872f556`.

Do not regenerate these files from a newly generated run. A compatibility
change must update the issue acceptance evidence and the golden set together.
