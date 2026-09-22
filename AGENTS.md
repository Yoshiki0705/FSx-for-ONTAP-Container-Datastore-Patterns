# AGENTS.md

Patterns for using Amazon FSx for NetApp ONTAP as the data store for
containerized workloads on Amazon ECS and Amazon EKS (EC2 and Fargate),
including workloads replatformed with AWS Transform containerization.

This file is read on every turn and cannot be made conditional, so it is an
index. The material lives in `docs/agent/`, tracked in git; `.kiro/` is
gitignored.

- [docs/agent/README.md](docs/agent/README.md) — index of project conventions,
  output standards (naming, vendor neutrality, public-output safety, JA/EN
  parity), and quality gates.

## Hub

This repository is a spoke of the Amazon FSx for NetApp ONTAP knowledge hub,
[FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook).
General ONTAP knowledge (block PV volume limits, multipath, Trident driver
choice) lives there and is cross-linked, not duplicated here.

## Run the gates

```bash
make install   # .venv を固定版で用意
make ci        # cfn-lint + headings + role-labels
```

Never commit VMware or ONTAP credentials, personal names, AWS account IDs, or
support case numbers. Details in
[docs/agent/output-standards.md](docs/agent/output-standards.md).
