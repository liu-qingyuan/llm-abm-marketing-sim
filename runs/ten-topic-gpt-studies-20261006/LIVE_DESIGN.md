# GPT-only merged bank collection and offline research

Study Module owns exact input/provenance, approved scope and ledger closure. Existing Pi Adapter owns the frozen GPT/P0 transport and observed response contract. Existing Kernel owns propagation. The run-local offline engine owns explicit historical draw anchoring and independent evidence. No public production Interface, paper, or canonical release changes.

## Architecture current
```mermaid
flowchart LR
  OldBank[Old bank] --> OldStudy[Historical studies]
  OldStudy --> OldKernel[Kernel]
  OldStudy --> OldEvidence[Old evidence]
```
## Architecture target
```mermaid
flowchart LR
  OldBank[Immutable old banks] --> Study[Merged input Study]
  Approval[Human GPT-only no total ceiling approval] --> Study
  Study --> Pi[Existing Pi GPT P0 Adapter]
  Pi --> Ledger[Intent settlement ledger]
  Ledger --> Recovery[Read only successful prefix and never attempted stage]
  Explicit[Separate human unknown reissue approval and actual success] --> Recovery
  Recovery --> Bank[Closed merged bank]
  Bank --> Kernel[Existing Kernel]
  Kernel --> Evidence[Independent rank draw barrier Evidence]
```
## Sequence current
```mermaid
sequenceDiagram
  participant S as Historical Study
  participant B as Old Bank
  participant K as Kernel
  S->>B: frozen lookup
  S->>K: bank hash draw identity
  K-->>S: old paths
```
## Sequence target
```mermaid
sequenceDiagram
  participant S as Study
  participant P as Pi Adapter
  participant B as Bank
  participant K as Kernel
  S->>S: verify human scope and exact source hashes
  loop missing unique inputs
    S->>S: fsync intent before dispatch
    S->>P: same GPT P0 request condition
    P-->>S: observed response and accounting
    S->>S: fsync settlement, stop unknown
  end
  S->>S: retain unknown, collect only never-attempted inputs
  opt separate explicit human reissue approval
    S->>P: one independently labeled new request
    P-->>S: verified new response; old unknown remains
  end
  S->>B: publish only complete exact bank
  loop 2800 paths
    S->>K: original seeds and explicit old draw anchor
    K-->>S: terminals and full batch barriers
  end
  S->>S: independent verification and old-new report
```
## State current
```mermaid
stateDiagram-v2
  [*] --> PendingFeeConfirmation
  PendingFeeConfirmation --> Blocked
```
## State target
```mermaid
stateDiagram-v2
  [*] --> HumanApproved
  HumanApproved --> Qualified
  Qualified --> Collecting
  Collecting --> Collecting: bounded per-input retry
  Collecting --> Partial: unknown or terminal failure
  Collecting --> BankClosed: all 17520 real judgments
  BankClosed --> Paths
  Paths --> Verified
  Verified --> Delivered
  Partial --> UnattemptedCollecting: new separate stage, no old key redispatch
  UnattemptedCollecting --> AwaitExplicitResolution
  AwaitExplicitResolution --> BankClosed: human approved new response and exact union
  AwaitExplicitResolution --> [*]: missing resolution retains partial
```
## Class current
```mermaid
classDiagram
  class HistoricalStudy
  class PiAdapter
  class Kernel
  HistoricalStudy --> PiAdapter
  HistoricalStudy --> Kernel
```
## Class target
```mermaid
classDiagram
  class MergedStudy
  class ImmutableApproval
  class PiAdapter
  class JudgmentBank
  class Kernel
  class RecoveryUnion
  class IndependentEvidence
  MergedStudy --> ImmutableApproval
  MergedStudy --> PiAdapter
  MergedStudy --> RecoveryUnion
  RecoveryUnion --> ImmutableApproval
  RecoveryUnion --> JudgmentBank
  JudgmentBank --> Kernel
  Kernel --> IndependentEvidence
```

Total financial/physical limits are explicitly unset by the user on 2026-10-06. This does not waive the original exact request condition, two retry limit per logical input, five in-flight transports, fsync ledger, unknown-stop rule, or response/model validation. Nominal accounting and unknown cash fees remain distinct.
