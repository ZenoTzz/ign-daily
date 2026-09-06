#!/usr/bin/env bash
# Shared maintenance gate lasts for the worker, data lock lasts only for commits.
with_worker_lock() {
  exec 8>"${IGN_DAILY_MAINTENANCE_LOCK:-/var/lock/ign-daily-maintenance.lock}"
  flock -sn 8 || { echo 'IGN_DAILY_MAINTENANCE: retry later'; exit 75; }
  exec 7>"${IGN_DAILY_WORKER_LOCK:-/var/lock/ign-daily-worker.lock}"
  flock -n 7 || { echo 'IGN_DAILY_WORKER_BUSY: retry later'; exit 75; }
  export IGN_DAILY_WRITE_LOCK="${IGN_DAILY_WRITE_LOCK:-/var/lock/ign-daily-write.lock}"
}
