"""Enroll an SSH node without putting credentials in shell history.

Example: python scripts/enroll_node.py --email admin@example.com --address 192.0.2.10 --username ssh-user
"""

import argparse
import getpass

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", default="Managed SSH node")
    parser.add_argument("--port", type=int, default=22)
    args = parser.parse_args()

    platform_password = getpass.getpass("Platform password: ")
    ssh_password = getpass.getpass("SSH password: ")
    with httpx.Client(base_url=args.api, timeout=30) as client:
        login = client.post("/api/auth/login", json={"email": args.email, "password": platform_password})
        login.raise_for_status()
        csrf = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        node = client.post("/api/nodes", headers=headers, json={
            "name": args.name,
            "address": args.address,
            "port": args.port,
            "username": args.username,
            "password": ssh_password,
        })
        node.raise_for_status()
        data = node.json()
        print(f"Enrolled node {data['id']} at {data['address']} with encrypted SSH credential.")
        checked = client.post(f"/api/nodes/{data['id']}/check", headers=headers)
        checked.raise_for_status()
        result = checked.json()
        print(f"Check: {result['status']} via {result.get('last_check_mode') or 'unknown'}")
        if result.get("last_error"):
            print(f"Error: {result['last_error']}")
        if result.get("facts"):
            print(f"Facts: {result['facts']}")


if __name__ == "__main__":
    main()
