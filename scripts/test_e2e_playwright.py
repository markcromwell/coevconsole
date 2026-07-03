import os
import re

import pytest


pytestmark = pytest.mark.skipif(
    not os.environ.get("COEV2_E2E_BASE_URL"),
    reason="COEV2_E2E_BASE_URL is required for the real CoEv2 happy-path fixture",
)


def test_submit_confirm_poll_render_against_real_coev2(page):
    base_url = os.environ["COEV2_E2E_BASE_URL"].rstrip("/")
    page.goto(base_url + "/")
    page.get_by_label("Grade input").fill("cheap/free CoEv2 grading fixture")
    page.get_by_role("button", name="Prepare grade").click()
    page.get_by_text(re.compile("may spend backend resources")).wait_for()
    page.get_by_role("button", name="Confirm and submit").click()
    page.get_by_text("Result").wait_for(timeout=30_000)
    page.get_by_text(re.compile("Score:")).wait_for()
    page.get_by_text("History").wait_for()
