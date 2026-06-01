Legacy one-off repair scripts.

These files were used for specific historical imports or article fixes. They
may contain hard-coded local paths and dates. Do not call them from cron,
heartbeat, or the normal translation workflow.

If a historical fix must be repeated, port the needed logic into a current
script that uses `scripts/common_paths.py`.

