"""Tests for dataset scheduler — crontab and systemd generation."""

from __future__ import annotations

from anysite.dataset.scheduler import ScheduleGenerator, _cron_to_oncalendar


class TestScheduleGenerator:
    def test_generate_crontab(self) -> None:
        gen = ScheduleGenerator("my-ds", "0 9 * * MON", "/path/to/dataset.yaml")
        entry = gen.generate_crontab()
        assert "0 9 * * MON" in entry
        assert "anysite dataset collect /path/to/dataset.yaml" in entry
        assert "my-ds_cron.log" in entry

    def test_generate_crontab_incremental(self) -> None:
        gen = ScheduleGenerator("my-ds", "0 9 * * *", "/path/to/dataset.yaml")
        entry = gen.generate_crontab(incremental=True)
        assert "--incremental" in entry

    def test_generate_systemd(self) -> None:
        gen = ScheduleGenerator("my-ds", "0 9 * * MON", "/path/to/dataset.yaml")
        units = gen.generate_systemd()

        assert "anysite-dataset-my-ds.service" in units
        assert "anysite-dataset-my-ds.timer" in units

        service = units["anysite-dataset-my-ds.service"]
        assert "anysite dataset collect" in service
        assert "my-ds" in service

        timer = units["anysite-dataset-my-ds.timer"]
        assert "OnCalendar=" in timer
        assert "timers.target" in timer

    def test_generate_systemd_incremental(self) -> None:
        gen = ScheduleGenerator("my-ds", "0 9 * * *", "/path/to/dataset.yaml")
        units = gen.generate_systemd(incremental=True)
        service = units["anysite-dataset-my-ds.service"]
        assert "--incremental" in service

    def test_no_schedule_value(self) -> None:
        gen = ScheduleGenerator("my-ds", "*/5 * * * *", "/path/to/dataset.yaml")
        entry = gen.generate_crontab()
        assert "*/5 * * * *" in entry


class TestCronToOnCalendar:
    def test_weekly_monday(self) -> None:
        result = _cron_to_oncalendar("0 9 * * MON")
        assert "Mon" in result
        assert "09" in result

    def test_daily(self) -> None:
        result = _cron_to_oncalendar("0 0 * * *")
        assert "00:00:00" in result

    def test_every_5_minutes(self) -> None:
        result = _cron_to_oncalendar("*/5 * * * *")
        assert "/5" in result

    def test_monthly(self) -> None:
        result = _cron_to_oncalendar("0 0 1 * *")
        assert "01" in result

    def test_passthrough_invalid(self) -> None:
        result = _cron_to_oncalendar("not a cron")
        assert result == "not a cron"
