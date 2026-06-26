#!/usr/bin/env python3
"""CLI wrapper around tamarind_client. Run it as a SCRIPT so the sibling import resolves
from ANY working directory: `python3 scripts/tamarind_job.py <command> ...`.

Python puts the script's own directory on sys.path[0], so `import tamarind_client` below
resolves whether your cwd is the skill root, /tmp, or anywhere else. (A bare
`from tamarind_client import ...` from an arbitrary cwd raises ModuleNotFoundError; this
wrapper is the copy-paste-safe entry point. Settings come from a JSON string or @file.)

Reads TAMARIND_API_KEY from the environment. Examples:

  python3 scripts/tamarind_job.py submit my-fold boltz '{"inputFormat":"sequence","sequence":"MKT..."}'
  python3 scripts/tamarind_job.py wait   my-fold
  python3 scripts/tamarind_job.py run    my-fold boltz @settings.json   # submit + wait + download
  python3 scripts/tamarind_job.py get    my-fold
  python3 scripts/tamarind_job.py upload target.pdb
  python3 scripts/tamarind_job.py download my-fold
"""
import argparse, json, sys

import tamarind_client as tc  # resolves from sys.path[0] == this script's dir


def _load_settings(arg):
    if arg.startswith("@"):
        with open(arg[1:]) as fh:
            return json.load(fh)
    return json.loads(arg)


def main(argv=None):
    p = argparse.ArgumentParser(prog="tamarind_job.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="POST /submit-job")
    s.add_argument("job_name"); s.add_argument("job_type")
    s.add_argument("settings", help='JSON string or @file.json')
    s.add_argument("--project-tag")

    w = sub.add_parser("wait", help="poll to a terminal status, print the final row")
    w.add_argument("job_name")
    w.add_argument("--interval", type=int, default=30)
    w.add_argument("--timeout", type=int, default=None)

    g = sub.add_parser("get", help="GET /jobs?jobName= (one read, print the row)")
    g.add_argument("job_name")

    d = sub.add_parser("download", help="two-step /result -> <job>.zip")
    d.add_argument("job_name"); d.add_argument("--out")

    u = sub.add_parser("upload", help="PUT /upload/<name>, print the bare filename")
    u.add_argument("local_path"); u.add_argument("--name"); u.add_argument("--folder")

    r = sub.add_parser("run", help="submit + wait + download in one call")
    r.add_argument("job_name"); r.add_argument("job_type")
    r.add_argument("settings", help='JSON string or @file.json')
    r.add_argument("--project-tag")
    r.add_argument("--interval", type=int, default=30)

    a = p.parse_args(argv)

    if a.cmd == "submit":
        print(tc.submit_job(a.job_name, a.job_type, _load_settings(a.settings), a.project_tag))
    elif a.cmd == "wait":
        print(json.dumps(tc.wait_for(a.job_name, interval=a.interval, timeout=a.timeout)))
    elif a.cmd == "get":
        print(json.dumps(tc.get_job(a.job_name)))
    elif a.cmd == "download":
        print(tc.download(a.job_name, out_path=a.out))
    elif a.cmd == "upload":
        print(tc.upload_file(a.local_path, registered_name=a.name, folder=a.folder))
    elif a.cmd == "run":
        print(tc.submit_job(a.job_name, a.job_type, _load_settings(a.settings), a.project_tag))
        tc.wait_for(a.job_name, interval=a.interval)
        print(tc.download(a.job_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
