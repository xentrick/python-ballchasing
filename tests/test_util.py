"""Helpers in ballchasing.util."""

from datetime import UTC, datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

import pytest

from ballchasing import util


class TestParseGroupId:
    GROUP_ID = "my-group-abc123"

    @pytest.mark.parametrize(
        "value",
        ["my-group-abc123", "abc", "group", "some/other/thing"],
    )
    def test_bare_ids_pass_through(self, value):
        assert util.parse_group_id(value) == value

    @pytest.mark.parametrize(
        "url",
        [
            "https://ballchasing.com/group/my-group-abc123",
            "http://ballchasing.com/group/my-group-abc123",
            # Trailing slash, query and fragment all come off the browser bar.
            "https://ballchasing.com/group/my-group-abc123/",
            "https://ballchasing.com/group/my-group-abc123?sort=created",
            "https://ballchasing.com/group/my-group-abc123#stats",
        ],
    )
    def test_extracts_id_from_group_urls(self, url):
        assert util.parse_group_id(url) == self.GROUP_ID

    def test_nested_group_url_returns_the_first_segment(self):
        url = "https://ballchasing.com/group/parent/child"
        assert util.parse_group_id(url) == "parent"

    def test_host_is_not_checked(self):
        """Only the path shape matters, so mirrors and localhost work too."""
        assert util.parse_group_id("https://example.invalid/group/abc") == "abc"

    @pytest.mark.parametrize(
        "url",
        [
            "https://ballchasing.com/replay/abc",
            "https://ballchasing.com/",
            "https://ballchasing.com/group/",
            "https://ballchasing.com/groups/abc",
        ],
    )
    def test_rejects_urls_that_are_not_groups(self, url):
        with pytest.raises(ValueError, match="Not a ballchasing group URL"):
            util.parse_group_id(url)

    def test_empty_string_passes_through(self):
        assert util.parse_group_id("") == ""


class TestParseRetryAfter:
    def test_none_when_header_absent(self):
        assert util.parse_retry_after(None) is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_none_when_blank(self, value):
        assert util.parse_retry_after(value) is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("30", 30.0), ("0", 0.0), ("1.5", 1.5), ("  12  ", 12.0)],
    )
    def test_parses_seconds(self, value, expected):
        assert util.parse_retry_after(value) == pytest.approx(expected)

    def test_negative_seconds_clamp_to_zero(self):
        assert util.parse_retry_after("-5") == 0.0

    def test_parses_http_date(self):
        when = datetime.now(UTC) + timedelta(seconds=120)
        parsed = util.parse_retry_after(format_datetime(when, usegmt=True))

        assert parsed is not None
        assert 115 <= parsed <= 121

    def test_past_http_date_clamps_to_zero(self):
        when = datetime.now(UTC) - timedelta(hours=1)
        assert util.parse_retry_after(format_datetime(when, usegmt=True)) == 0.0

    @pytest.mark.parametrize("value", ["soon", "not-a-date", "Tue, 99 Xyz 2024"])
    def test_none_when_unparseable(self, value):
        assert util.parse_retry_after(value) is None


class TestRfc3339:
    def test_none_passes_through(self):
        assert util.rfc3339(None) is None

    def test_strings_pass_through_untouched(self):
        assert util.rfc3339("2024-01-02T03:04:05Z") == "2024-01-02T03:04:05Z"

    def test_naive_datetime_is_assumed_utc(self):
        naive = datetime(2024, 1, 2, 3, 4, 5)  # noqa: DTZ001 -- naive is the point
        assert util.rfc3339(naive) == "2024-01-02T03:04:05Z"

    def test_aware_utc_uses_z_suffix(self):
        value = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert util.rfc3339(value) == "2024-01-02T03:04:05Z"

    def test_non_utc_offset_is_preserved(self):
        value = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2)))
        assert util.rfc3339(value) == "2024-01-02T03:04:05+02:00"

    def test_rejects_other_types(self):
        with pytest.raises(ValueError, match="string or datetime"):
            util.rfc3339(12345)


class TestLogFormData:
    def test_ignores_non_formdata(self, caplog):
        not_form: Any = "not form data"
        with caplog.at_level("DEBUG", logger="ballchasing.util"):
            util.log_form_data(not_form)
        assert "Not a FormData instance" in caplog.text

    def test_logs_field_summaries(self, caplog):
        from aiohttp import FormData

        form = FormData()
        form.add_field("file", b"abc", filename="x.replay")
        form.add_field("name", "value")

        with caplog.at_level("DEBUG", logger="ballchasing.util"):
            util.log_form_data(form)

        assert "binary data, 3 bytes" in caplog.text
        assert "value" in caplog.text
