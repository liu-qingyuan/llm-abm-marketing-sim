"""Allowlisted classifications of local SDK errors; never persist exception text."""

STATIC_CASES = {
    "Pi subscription request timed out without verifiable response provenance": "timeout_unreconciled",
    "Pi subscription request ended without verifiable response provenance": "eof_unreconciled",
    "Pi subscription request returned an unverifiable response": "malformed_rpc_json",
    "Pi subscription request response identity could not be reconciled": "crossed_rpc_identity",
    "Pi subscription request dispatch could not be reconciled": "dispatch_unreconciled",
}


def classify(exc):
    return STATIC_CASES.get(str(exc), "unclassified_unknown")
