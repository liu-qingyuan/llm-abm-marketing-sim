# Segmented Full-Pool source-v2 consumer and release v9

Status: implementation architecture note

This note records the local, offline consumer path for `full-pool-segmented-source-v2`. It does not claim that a live source exists and does not authorize Provider calls, SSH, public-network validation, or canonical cutover. The existing Full-Pool source-v1 and `abm-report-release-contract-v8` paths remain exact compatibility paths.

## Architecture and call relationships — current

```mermaid
flowchart LR
  V1["Full-Pool source-v1"] --> Reader["FullPool source reader"]
  Reader --> Report["Report Module"]
  Report --> Evidence["Evidence Module"]
  Evidence --> Release["Release Module v8"]
  Release --> Deploy["Deployment validator"]
  V2["Segmented source-v2"] --> Stop["No Report or Release consumer"]
```

## Architecture and call relationships — target

```mermaid
flowchart LR
  V1["Full-Pool source-v1"] --> Dispatch["Version-dispatched source reader"]
  V2["Segmented source-v2 plus cutoff lineage"] --> Dispatch
  Dispatch --> Facts["Typed closed source facts"]
  Facts --> Report["Existing Report Seam"]
  Report --> Evidence["Existing Evidence Seam"]
  Evidence --> Release["Release Module exact v8 or v9 dispatch"]
  Release --> Deploy["Existing Deployment Seam allowlist"]
  V1 --> V8["v8 unchanged"]
  V2 --> V9["v9 only"]
```

## Sequence — current

```mermaid
sequenceDiagram
  participant Caller
  participant Report
  participant V1Reader
  participant Release
  Caller->>Report: compose Full-Pool candidate with source-v1
  Report->>V1Reader: close explicit source and manifest hash
  V1Reader-->>Report: immutable source view
  Report-->>Caller: nondeployable candidate
  Caller->>Release: promote exact v8 inputs
  Release-->>Caller: local production release and v8 contract
```

## Sequence — target

```mermaid
sequenceDiagram
  participant Caller
  participant SourceReader
  participant Report
  participant Evidence
  participant Release
  participant DeployValidator
  Caller->>SourceReader: close explicit segmented source-v2
  SourceReader->>SourceReader: verify rows, order, feedback, accounting, cutoff and hashes
  SourceReader-->>Caller: typed segmented facts
  Caller->>Report: compose candidate through existing Seam
  Report-->>Caller: candidate marked nondeployable
  Caller->>Evidence: close candidate and segmented lineage
  Evidence-->>Caller: typed v9 production evidence
  Caller->>Release: promote exact v9 contract with zero Provider calls
  Release-->>Caller: immutable local release and v9 contract
  Caller->>DeployValidator: require formal production preflight
  DeployValidator-->>Caller: local deployment facts only
```

## State — current

```mermaid
stateDiagram-v2
  [*] --> SegmentedProduced
  SegmentedProduced --> RuntimeReplayable
  RuntimeReplayable --> [*]
  SegmentedProduced --> ConsumerRejected: no source-v2 dispatch
  ConsumerRejected --> [*]
```

## State — target

```mermaid
stateDiagram-v2
  [*] --> SourceV2Presented
  SourceV2Presented --> SourceClosed: exact validator passes
  SourceV2Presented --> Rejected: tamper count topology or accounting fails
  SourceClosed --> CandidateClosed: Report and Evidence zero-call closure
  CandidateClosed --> V9Promoted: live Formal facts and exact v9 contract pass
  CandidateClosed --> Rejected: Validation or mock source
  V9Promoted --> DeploymentPreflightPassed: local allowlist and snapshot pass
  DeploymentPreflightPassed --> AwaitingOperator: no SSH network or cutover in tests
  Rejected --> [*]
  AwaitingOperator --> [*]
```

## Class and Interface structure — current

```mermaid
classDiagram
  class ClosedFullPoolSourceV1 {
    +root
    +contract
    +manifest
    +aggregates
    +diagnostics
    +read_batch()
  }
  class ReportPresentation {
    +compose_full_pool_candidate()
    +validate_full_pool_candidate()
  }
  class FullPoolFormalReleaseFacts
  ClosedFullPoolSourceV1 --> ReportPresentation
  ReportPresentation --> FullPoolFormalReleaseFacts
```

## Class and Interface structure — target

```mermaid
classDiagram
  class ClosedFullPoolSource {
    +root
    +contract
    +manifest
    +aggregates
    +diagnostics
    +read_batch()
  }
  class SegmentedSourceFacts {
    +source_identity
    +cutoff_identity
    +prefix_terminal_count
    +suffix_terminal_count
    +logical_count
    +physical_attempt_count
    +migration_charge
  }
  class VersionDispatchedSourceReader {
    +read(source_root manifest_sha256)
  }
  class ReportPresentation {
    +compose_full_pool_candidate()
    +validate_full_pool_candidate()
  }
  class V9FormalReleaseFacts
  VersionDispatchedSourceReader --> ClosedFullPoolSource
  VersionDispatchedSourceReader --> SegmentedSourceFacts
  ClosedFullPoolSource --> ReportPresentation
  SegmentedSourceFacts --> V9FormalReleaseFacts
  ReportPresentation --> V9FormalReleaseFacts
```

## Compatibility and ownership

- The segmented validator owns source-v2 row, accounting, cutoff, continuation identity, and artifact-hash knowledge.
- Report consumes the same closed-source Interface and only adds segmented method/lineage facts; it does not decide production eligibility.
- Evidence re-closes candidate bytes and typed segmented facts; Validation/mock classifications remain non-production.
- Release owns exact v9 eligibility, inventory, release identity, and promotion. v8 fields and dispatch are not widened.
- Deployment continues through the existing standalone validator and shell Seam. The only additive deployment change is the v9 schema allowlist and corresponding public-acceptance contract.
