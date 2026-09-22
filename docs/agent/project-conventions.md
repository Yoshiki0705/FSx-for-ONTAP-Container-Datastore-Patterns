# Project conventions

Patterns for using Amazon FSx for NetApp ONTAP as the data store for
containerized workloads on Amazon ECS and Amazon EKS. The repository documents
and provides CloudFormation for several access forms (NFS/SMB host mount on ECS
EC2, NetApp Trident persistent volumes on EKS EC2, and S3 Access Points object
access on Fargate), including workloads replatformed with AWS Transform
containerization.

## Directory layout

```
docs/ja/     日本語ドキュメント（主）
docs/en/     英語ドキュメント
docs/agent/  エージェント向け（この階層）
.private/    非公開。gitignore 対象
templates/   CloudFormation
params/      テンプレートのパラメータ例
tools/       ゲート検査スクリプト
```

## Language and style

- CloudFormation YAML for infrastructure. Lint with cfn-lint.
- Documentation is bilingual: JA is primary, EN must match section structure and
  count. Change both in the same commit.

## Hub relationship

This repository is a spoke of
[FSx-for-ONTAP-Adoption-Playbook](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook),
the Amazon FSx for NetApp ONTAP knowledge hub. General ONTAP knowledge (block
persistent-volume limits, multipath, Trident driver choice) lives in the hub and
is cross-linked, not duplicated here. This repository covers only the container
data-store patterns.

> **EN cross-link note**: the hub's block-storage domain has JA notes but the EN
> individual notes are not yet published (only the domain README and quickstart
> exist on the hub's main branch as of 2026-09-22). EN documents here therefore
> complete the point in-body rather than link to a hub EN note that would 404.
> Add the EN cross-link once the hub publishes the EN note.

## Related repository

The VMware ESXi to Amazon EC2 + FSx for ONTAP rehost migration verification
(NetApp Shift Toolkit, AWS Transform for migrations, AD integration) lives in
[VMware-Migration-EC2-ONTAP](https://github.com/Yoshiki0705/vmware-migration-ec2-ontap).
The SMB CloudFormation here references an existing directory (`DirectoryId`); set
up the Active Directory side there or with an AWS Managed Microsoft AD.

## Credentials

VMware and ONTAP credentials never enter the repository. `params/*.example.json`
carries the shape; real values stay outside version control.
