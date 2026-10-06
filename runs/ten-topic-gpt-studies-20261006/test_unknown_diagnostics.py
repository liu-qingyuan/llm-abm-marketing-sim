import unknown_diagnostics as diagnostic
from llm_abm_sim.decision import ProviderResponseProvenanceUnknown


def test_timeout_exact_static_case():
    assert (
        diagnostic.classify(
            ProviderResponseProvenanceUnknown(
                "Pi subscription request timed out without verifiable response provenance"
            )
        )
        == "timeout_unreconciled"
    )


def test_unrecognized_text_is_never_persisted():
    assert diagnostic.classify(RuntimeError("UNIT_TEST_UNTRUSTED_TEXT")) == "unclassified_unknown"
