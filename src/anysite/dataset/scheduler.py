"""Schedule generation for dataset collection — crontab and systemd."""

from __future__ import annotations

import shutil


class ScheduleGenerator:
    """Generate crontab or systemd timer entries for dataset collection."""

    def __init__(self, dataset_name: str, cron_expr: str, yaml_path: str) -> None:
        self.dataset_name = dataset_name
        self.cron = cron_expr
        self.yaml_path = yaml_path

    def generate_crontab(self, *, incremental: bool = False, load_db: str | None = None) -> str:
        """Generate a crontab entry."""
        anysite = shutil.which("anysite") or "anysite"
        cmd = f"{anysite} dataset collect {self.yaml_path}"
        if incremental:
            cmd += " --incremental"
        if load_db:
            cmd += f" --load-db {load_db}"
        return f"{self.cron} {cmd} >> ~/.anysite/logs/{self.dataset_name}_cron.log 2>&1"

    def generate_systemd(self, *, incremental: bool = False, load_db: str | None = None) -> dict[str, str]:
        """Generate systemd service and timer unit files."""
        anysite = shutil.which("anysite") or "anysite"
        cmd = f"{anysite} dataset collect {self.yaml_path}"
        if incremental:
            cmd += " --incremental"
        if load_db:
            cmd += f" --load-db {load_db}"

        service_name = f"anysite-dataset-{self.dataset_name}"
        on_calendar = _cron_to_oncalendar(self.cron)

        service = f"""[Unit]
Description=Anysite dataset collection: {self.dataset_name}

[Service]
Type=oneshot
ExecStart={cmd}
StandardOutput=journal
StandardError=journal
"""

        timer = f"""[Unit]
Description=Timer for anysite dataset: {self.dataset_name}

[Timer]
OnCalendar={on_calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""

        return {
            f"{service_name}.service": service,
            f"{service_name}.timer": timer,
        }


def _cron_to_oncalendar(cron: str) -> str:
    """Convert a cron expression to systemd OnCalendar format (best effort).

    Handles common patterns:
        0 9 * * MON   -> Mon *-*-* 09:00:00
        */5 * * * *   -> *-*-* *:0/5:00
        0 0 1 * *     -> *-*-01 00:00:00
    """
    parts = cron.split()
    if len(parts) != 5:
        return cron  # pass through as-is

    minute, hour, day, month, dow = parts

    # Day-of-week mapping
    dow_map = {
        "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
        "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun",
        "MON": "Mon", "TUE": "Tue", "WED": "Wed",
        "THU": "Thu", "FRI": "Fri", "SAT": "Sat", "SUN": "Sun",
    }

    # Format components
    dow_str = ""
    if dow != "*":
        dow_parts = dow.replace(",", " ").split()
        dow_str = ",".join(dow_map.get(d.upper(), d) for d in dow_parts) + " "

    month_str = month if month != "*" else "*"
    day_str = day.zfill(2) if day != "*" and "/" not in day else day

    hour_str = hour.zfill(2) if hour != "*" and "/" not in hour else hour
    min_str = minute.zfill(2) if minute != "*" and "/" not in minute else minute

    # Handle step values
    if "/" in minute:
        base, step = minute.split("/")
        min_str = f"{base or '0'}/{step}"
    if "/" in hour:
        base, step = hour.split("/")
        hour_str = f"{base or '0'}/{step}"

    return f"{dow_str}*-{month_str}-{day_str} {hour_str}:{min_str}:00"
