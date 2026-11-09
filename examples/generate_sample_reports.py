"""Generate a realistic set of JUnit XML reports to try flakelens with.

Simulates 12 CI runs of a small e-commerce test suite containing:

* stable tests that always pass,
* flaky tests that fail randomly (timeouts, race conditions...),
* a regression that starts failing from run 8 onward,
* a test that is always skipped.

The output is deterministic (fixed random seed), so the examples in the
README stay reproducible.

Usage:
    python examples/generate_sample_reports.py [OUTPUT_DIR] [--runs N]
"""

from __future__ import annotations

import argparse
import random
import xml.etree.ElementTree as ET
from pathlib import Path

SEED = 42

# test id -> probability of failing on any given run
FLAKY_TESTS = {
    "tests.test_checkout::test_payment_gateway_timeout": 0.35,
    "tests.test_notifications::test_websocket_receives_order_update": 0.25,
    "tests.test_search::test_autocomplete_suggestions": 0.15,
}
STABLE_TESTS = [
    "tests.test_auth::test_login_with_valid_credentials",
    "tests.test_auth::test_login_rejects_wrong_password",
    "tests.test_cart::test_add_item",
    "tests.test_cart::test_remove_item",
    "tests.test_search::test_search_by_product_name",
    "tests.test_profile::test_update_shipping_address",
]
REGRESSION_TEST = "tests.test_promotions::test_expired_coupon_is_rejected"
REGRESSION_STARTS_AT_RUN = 8
SKIPPED_TEST = "tests.test_legacy::test_export_to_xls"

FAILURE_MESSAGES = {
    "tests.test_checkout::test_payment_gateway_timeout": "TimeoutError: gateway did not respond in 5s",
    "tests.test_notifications::test_websocket_receives_order_update": "AssertionError: expected 1 message, got 0",
    "tests.test_search::test_autocomplete_suggestions": "ElementNotFound: #suggestions not visible after 2s",
    REGRESSION_TEST: "AssertionError: expected HTTP 400, got 200",
}


def build_report(run_number: int, rng: random.Random) -> ET.ElementTree:
    suites = ET.Element("testsuites")
    suite = ET.SubElement(suites, "testsuite", name=f"ci-run-{run_number:02d}")

    def add_case(test_id: str, outcome: str) -> None:
        classname, _, name = test_id.rpartition("::")
        case = ET.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=name,
            time=f"{rng.uniform(0.05, 3.0):.3f}",
        )
        if outcome == "failed":
            failure = ET.SubElement(case, "failure", message=FAILURE_MESSAGES[test_id])
            failure.text = f"Traceback (most recent call last):\n  ...\n{FAILURE_MESSAGES[test_id]}"
        elif outcome == "skipped":
            ET.SubElement(case, "skipped", message="legacy export disabled")

    for test_id in STABLE_TESTS:
        add_case(test_id, "passed")
    for test_id, fail_probability in FLAKY_TESTS.items():
        add_case(test_id, "failed" if rng.random() < fail_probability else "passed")
    add_case(REGRESSION_TEST, "failed" if run_number >= REGRESSION_STARTS_AT_RUN else "passed")
    add_case(SKIPPED_TEST, "skipped")

    ET.indent(suites)
    return ET.ElementTree(suites)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=Path(__file__).parent / "reports",
        type=Path,
    )
    parser.add_argument("--runs", type=int, default=12)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    for run_number in range(1, args.runs + 1):
        path = args.output_dir / f"run-{run_number:02d}.xml"
        build_report(run_number, rng).write(path, encoding="utf-8", xml_declaration=True)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
